"""Phase-1 test: historical ACTIVITY fetch (last 2h)."""
import asyncio
from datetime import datetime, timedelta

import helio
helio.DEBUG = False
from helio import HelioClient, load_auth_key, FT_ACTIVITY
import fetch


async def main():
    c = HelioClient(load_auth_key())
    if not await c.connect_and_auth():
        print("auth failed")
        return
    since = datetime.now() - timedelta(hours=2)
    print(f"\n=== ACTIVITY fetch since {since:%Y-%m-%d %H:%M} ===")
    try:
        start_dt, buf, exp, valid = await c._fetch_once(FT_ACTIVITY, since)
        print(f"  handshake OK: expected_len={exp}  start_dt={start_dt}  got={len(buf)}B  valid={valid}")
        rows = fetch.parse_activity(start_dt, buf)
        print(f"  parsed {len(rows)} minute-samples; last 12:")
        for r in rows[-12:]:
            t = datetime.fromtimestamp(r["ts"] / 1000).strftime("%H:%M")
            print(f"    {t}  steps+{r['steps']:>3}  hr={r['hr']:>3}  "
                  f"sleep={r['sleep']}/{r['deep_sleep']}/{r['rem_sleep']}")
        tot = sum(r["steps"] for r in rows)
        hrs = [r["hr"] for r in rows if 0 < r["hr"] < 255]
        print(f"  -> {tot} steps in window; {len(hrs)} hr samples, "
              f"avg={sum(hrs) // len(hrs) if hrs else 0}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  fetch error: {e}")
    await asyncio.sleep(0.3)
    await c.close()


if __name__ == "__main__":
    asyncio.run(main())
