import logging
import os
import threading

from .server import serve
from .service import CheckerService


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not os.environ.get("GITHUB_TOKEN"):
        raise SystemExit("GITHUB_TOKEN must be set in .env")
    service = CheckerService()
    threading.Thread(target=service.loop, name="verification-scheduler", daemon=True).start()
    serve(service)


if __name__ == "__main__":
    main()
