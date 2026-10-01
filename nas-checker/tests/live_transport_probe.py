"""Read-only live verification; never publish or read NAS credentials."""
import asyncio
import json
import time

from signal_nas.browser import BrowserVerifier


async def main():
    for key, url in (("sbxh", "https://sbxh9.com"), ("newtoki", "https://newtoki1.org"), ("toki", "https://toki32.com")):
        started = time.monotonic()
        async with BrowserVerifier() as browser:
            result, reason = await browser.verify(key, url, allow_protected=True)
        print(json.dumps(dict(key=key, result=result, reason=reason,
                              elapsedMs=round((time.monotonic() - started) * 1000)), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
