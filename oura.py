"""
Oura Ring -> data/oura.json  via the official Oura API v2 (read-only).

Token: a Personal Access Token from https://cloud.ouraring.com/personal-access-tokens
  -> put it in oura-token.local.txt (gitignored), or set env OURA_TOKEN.

Pulls the last 30 days of sleep (stages, HRV, SpO2, resting HR), readiness, daily SpO2,
and activity. Defensive parsing: unknown fields just become null.

Use standalone:  python3 oura.py
Or from the collector:  oura.refresh()  (returns the dict, or None if no token).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

BASE = "https://api.ouraring.com/v2/usercollection/"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
OURA_JSON = os.path.join(DATA_DIR, "oura.json")
DAYS = 30


def maybe_token():
    t = os.environ.get("OURA_TOKEN")
    if t:
        return t.strip()
    p = os.path.join(HERE, "oura-token.local.txt")
    if os.path.exists(p):
        with open(p) as f:
            tok = f.read().strip()
        return tok or None
    return None


def _get(token, endpoint, params):
    url = BASE + endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("data", [])


def _iso_ms(s):
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return None


def fetch_all(token, days=DAYS):
    end = date.today()
    s, e = (end - timedelta(days=days)).isoformat(), end.isoformat()
    sleep = _get(token, "sleep", {"start_date": s, "end_date": e})
    readiness = _get(token, "daily_readiness", {"start_date": s, "end_date": e})
    daily_sleep = _get(token, "daily_sleep", {"start_date": s, "end_date": e})
    spo2 = _get(token, "daily_spo2", {"start_date": s, "end_date": e})
    activity = _get(token, "daily_activity", {"start_date": s, "end_date": e})
    # intraday HR time-series (densest the cloud has; refreshes on each ring sync /
    # when you use the app's Live HR / Workout feature)
    now = datetime.now(timezone.utc)
    heartrate = _get(token, "heartrate", {
        "start_datetime": (now - timedelta(hours=48)).isoformat(),
        "end_datetime": now.isoformat(),
    })

    def h(seconds):
        return round((seconds or 0) / 3600, 2)

    nights = []
    for n in sleep:
        if n.get("type") not in ("long_sleep", "sleep", None):
            continue  # skip naps; keep the main night
        nights.append({
            "day": n.get("day"),
            "total_h": h(n.get("total_sleep_duration")),
            "deep_h": h(n.get("deep_sleep_duration")),
            "rem_h": h(n.get("rem_sleep_duration")),
            "light_h": h(n.get("light_sleep_duration")),
            "hrv": n.get("average_hrv"),
            "resting_hr": n.get("lowest_heart_rate"),
            "avg_hr": n.get("average_heart_rate"),
            "spo2": (n.get("spo2_percentage") or {}).get("average"),
            "efficiency": n.get("efficiency"),
            "bedtime_start": n.get("bedtime_start"),
            "time_in_bed_h": h(n.get("time_in_bed")),
        })

    return {
        "updated": int(time.time() * 1000),
        "nights": nights,
        "readiness": [{"day": r.get("day"), "score": r.get("score")} for r in readiness],
        "sleep_score": [{"day": r.get("day"), "score": r.get("score")} for r in daily_sleep],
        "spo2": [{"day": r.get("day"), "spo2": (r.get("spo2_percentage") or {}).get("average")} for r in spo2],
        "activity": [{"day": r.get("day"), "steps": r.get("steps"),
                      "active_cal": r.get("active_calories")} for r in activity],
        "heartrate": [{"t": _iso_ms(h.get("timestamp")), "bpm": h.get("bpm"),
                       "source": h.get("source")} for h in heartrate if h.get("bpm")],
        "_raw_sleep_keys": sorted(sleep[0].keys()) if sleep else [],
    }


def _write(out):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = OURA_JSON + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f)
    os.replace(tmp, OURA_JSON)


def refresh():
    """Fetch + write data/oura.json. Returns the dict, or None if no token / on error."""
    token = maybe_token()
    if not token:
        return None
    try:
        out = fetch_all(token)
    except urllib.error.HTTPError as ex:
        print(f"[oura] API error {ex.code}: {ex.read().decode(errors='replace')[:160]}")
        return None
    except Exception as ex:  # network etc — don't kill the collector
        print(f"[oura] fetch failed: {ex}")
        return None
    _write(out)
    return out


def main():
    if maybe_token() is None:
        sys.exit("No Oura token. Put it in oura-token.local.txt or set OURA_TOKEN "
                 "(get one at https://cloud.ouraring.com/personal-access-tokens).")
    out = refresh()
    if not out:
        sys.exit("Oura fetch failed (see message above).")
    print("first sleep record keys:", out.get("_raw_sleep_keys"))
    print(f"Oura -> {len(out['nights'])} nights, {len(out['readiness'])} readiness, "
          f"{len(out['spo2'])} spo2, {len(out['activity'])} activity days, "
          f"{len(out['heartrate'])} HR samples -> data/oura.json")
    if out["heartrate"]:
        hrs = out["heartrate"]
        last = hrs[-1]
        srcs = sorted({h['source'] for h in hrs if h.get('source')})
        print(f"  HR: {len(hrs)} samples (sources: {srcs}); latest "
              f"{last['bpm']} bpm @ {datetime.fromtimestamp(last['t']/1000)}")
    if out["nights"]:
        L = out["nights"][-1]
        print(f"  last night {L['day']}: {L['total_h']}h sleep "
              f"(deep {L['deep_h']}h / rem {L['rem_h']}h), HRV {L['hrv']}, "
              f"resting HR {L['resting_hr']}, SpO2 {L['spo2']}%")


if __name__ == "__main__":
    main()
