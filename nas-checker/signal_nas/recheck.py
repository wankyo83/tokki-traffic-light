"""One verified repair cycle. Run only while the scheduled checker is stopped."""
import json
import sys
from .model import BY_KEY
from .service import CheckerService

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in BY_KEY:
        raise SystemExit('Usage: python -m signal_nas.recheck SITE_KEY')
    service = CheckerService()
    service.run_once({sys.argv[1]})
    snapshot = service.snapshot()
    if snapshot['lastError']:
        raise SystemExit(snapshot['lastError'])
    print(json.dumps({'commit': snapshot['lastCommit'], 'groups': [group for group in snapshot['groups']
                       if group['key'] == sys.argv[1]]}, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    main()
