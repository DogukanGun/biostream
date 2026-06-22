"""
Deprecated entry point — the collector is now split into:
  authenticator.py (auth) + store.py (persistence) + worker.py (the collect loop).
This shim keeps `python3 collector.py` working. Prefer `python3 worker.py`.
"""
import asyncio

from worker import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped.")
