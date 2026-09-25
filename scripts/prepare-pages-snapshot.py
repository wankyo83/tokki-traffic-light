"""Use the newer of checkout/public JSON only in the ephemeral Pages build directory.

The NAS publishes JSON by Git API. A simultaneous UI-only commit may be based on an
older checkout; deploying that checkout must never roll the addresses backwards.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = "https://wankyo83.github.io/tokki-traffic-light"


def when(document, key):
    return datetime.fromisoformat(document[key].replace("Z", "+00:00"))


for filename, field in (("domains.json", "updatedAt"), ("status.json", "checkedAt")):
    path = Path("site") / filename
    local = json.loads(path.read_text(encoding="utf-8"))
    request = Request(f"{ROOT}/{filename}?prepare={time.time_ns()}", headers={"Cache-Control": "no-cache"})
    with urlopen(request, timeout=20) as response:
        public = json.load(response)
    if when(local, field) <= when(public, field):
        path.write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{filename}: retained current published snapshot")
    else:
        print(f"{filename}: using newer NAS-verified checkout snapshot")
