"""Fail closed if a Pages deployment would roll back the published address snapshot."""

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen


BASE_URL = "https://wankyo83.github.io/tokki-traffic-light"


def timestamp(document, field):
    value = document.get(field)
    if not isinstance(value, str):
        raise ValueError(f"Missing {field}")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def check(filename, field):
    local = json.loads(Path("site", filename).read_text(encoding="utf-8"))
    request = Request(
        f"{BASE_URL}/{filename}?publish_guard={time.time_ns()}",
        headers={"Cache-Control": "no-cache"},
    )
    with urlopen(request, timeout=20) as response:
        published = json.load(response)
    local_time = timestamp(local, field)
    published_time = timestamp(published, field)
    if local_time < published_time or (local_time == published_time and local != published):
        raise ValueError(
            f"site/{filename} is older than the published copy; sync the live snapshot before deploying"
        )
    print(f"site/{filename}: publication guard passed")


try:
    check("domains.json", "updatedAt")
    check("status.json", "checkedAt")
except Exception as error:
    print(f"Pages deployment blocked: {error}", file=sys.stderr)
    sys.exit(1)
