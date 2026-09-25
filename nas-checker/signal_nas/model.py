import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit


ROOT = Path(__file__).resolve().parent.parent
SITES = json.loads((ROOT / "config/sites.json").read_text(encoding="utf-8"))
RULES = json.loads((ROOT / "config/verification-rules.json").read_text(encoding="utf-8"))["rules"]
BY_KEY = {site["key"]: site for site in SITES}
CHALLENGE_MARKERS = ("just a moment", "checking your browser", "verify you are human", "cf-chl", "_cf_chl_opt", "cloudflare ray id", "잠시만 기다려")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def validate_url(key, raw):
    if key not in RULES or not isinstance(raw, str) or len(raw) > 300:
        raise ValueError("unknown site or invalid URL")
    try:
        parsed = urlsplit(raw.strip())
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid URL") from exc
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or port not in (None, 443):
        raise ValueError("HTTPS site URL without credentials or custom port required")
    if not re.fullmatch(RULES[key]["hostPattern"], parsed.hostname.lower()):
        raise ValueError("URL is outside the configured site family")
    return f"https://{parsed.hostname.lower()}"


def host_candidates(key, text):
    """Extract URLs only from the known site family, never arbitrary guide links."""
    found = []
    pattern = re.compile(r"(?:https?://)?(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s\"'<>]*)?", re.I)
    for match in pattern.finditer(text or ""):
        candidate = match.group(0).rstrip(".,;:)\u3002")
        if not candidate.startswith(("http://", "https://")):
            candidate = "https://" + candidate
        try:
            normalized = validate_url(key, candidate)
        except ValueError:
            continue
        if normalized not in found:
            found.append(normalized)
    return found


def numeric_candidates(key, current, count=10, start_offset=1):
    """Try only the next numbered addresses in the current site's family."""
    try:
        current = validate_url(key, current)
    except ValueError:
        return []
    host = urlsplit(current).hostname
    match = re.search(r"^(?P<prefix>(?:www\.)?[a-z]+)(?P<number>\d+)(?P<suffix>\.[a-z]+)$", host)
    if not match:
        return []
    number = int(match["number"])
    width = len(match["number"])
    candidates = [f"https://{match['prefix']}{value:0{width}d}{match['suffix']}" for value in range(number + start_offset, number + start_offset + count)]
    return [url for url in candidates if url != current]


def automatic_regression(key, current, candidate):
    """Reject stale guide URLs; jjaptoon's documented numbering reset is allowed."""
    if key == "jjaptoon" or not current or not candidate:
        return False
    try:
        old = validate_url(key, current)
        new = validate_url(key, candidate)
    except ValueError:
        return True
    old_number = re.search(r"\d+", urlsplit(old).hostname or "")
    new_number = re.search(r"\d+", urlsplit(new).hostname or "")
    return bool(old_number and new_number and int(new_number.group()) < int(old_number.group()))


def matches_category(base_url, candidate_url, category_path):
    base = urlsplit(base_url)
    candidate = urlsplit(candidate_url)
    expected = urlsplit(category_path)
    if candidate.hostname != base.hostname or candidate.scheme != "https":
        return False
    if unquote(candidate.path).rstrip("/") != unquote(expected.path).rstrip("/"):
        return False
    if expected.fragment and candidate.fragment != expected.fragment:
        return False
    expected_query = parse_qsl(expected.query, keep_blank_values=True)
    actual_query = parse_qsl(candidate.query, keep_blank_values=True)
    return all(pair in actual_query for pair in expected_query)


def validate_page(key, final_url, title, body_text, links, html, status=200, requested_category=None):
    try:
        base = validate_url(key, final_url)
    except ValueError as exc:
        return None, str(exc)
    if status < 200 or status >= 400:
        return None, f"HTTP {status}"
    sample = (title + " " + body_text[:120_000]).lower()
    html_head = html[:120_000].lower()
    if any(marker in sample or marker in html_head for marker in CHALLENGE_MARKERS):
        return None, "Cloudflare challenge remains"
    paths = RULES[key].get("categoryPaths", [])
    if not paths:
        return None, "no category routes configured"
    for path in paths:
        if requested_category and path == requested_category and not urlsplit(path).fragment and matches_category(base, final_url, path):
            if body_text.strip() or len(html) > 200:
                return base, f"category route verified: {path}"
        if any(matches_category(base, link.get("href", ""), path) for link in links):
            return base, f"category navigation verified: {path}"
    return None, "category navigation not found"


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
