"""
Oura Ring -> dict via the official Oura API v2 (read-only).
Config-driven: token + base url + window passed in; no module-level paths or secrets.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

DEFAULT_BASE = "https://api.ouraring.com/v2/usercollection/"


def _get(token, base, endpoint, params):
    url = base + endpoint + "?" + urllib.parse.urlencode(params)
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


def fetch_all(token, base=DEFAULT_BASE, days=30):
    end = date.today()
    s, e = (end - timedelta(days=days)).isoformat(), end.isoformat()
    sleep = _get(token, base, "sleep", {"start_date": s, "end_date": e})
    readiness = _get(token, base, "daily_readiness", {"start_date": s, "end_date": e})
    daily_sleep = _get(token, base, "daily_sleep", {"start_date": s, "end_date": e})
    spo2 = _get(token, base, "daily_spo2", {"start_date": s, "end_date": e})
    activity = _get(token, base, "daily_activity", {"start_date": s, "end_date": e})
    now = datetime.now(timezone.utc)
    heartrate = _get(token, base, "heartrate", {
        "start_datetime": (now - timedelta(hours=48)).isoformat(),
        "end_datetime": now.isoformat(),
    })

    def h(seconds):
        return round((seconds or 0) / 3600, 2)

    nights = []
    for n in sleep:
        if n.get("type") not in ("long_sleep", "sleep", None):
            continue
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
        "updated": int(datetime.now().timestamp() * 1000),
        "nights": nights,
        "readiness": [{"day": r.get("day"), "score": r.get("score")} for r in readiness],
        "sleep_score": [{"day": r.get("day"), "score": r.get("score")} for r in daily_sleep],
        "spo2": [{"day": r.get("day"), "spo2": (r.get("spo2_percentage") or {}).get("average")} for r in spo2],
        "activity": [{"day": r.get("day"), "steps": r.get("steps"),
                      "active_cal": r.get("active_calories")} for r in activity],
        "heartrate": [{"t": _iso_ms(h_.get("timestamp")), "bpm": h_.get("bpm"),
                       "source": h_.get("source")} for h_ in heartrate if h_.get("bpm")],
    }


def write(out, path):
    path = os.fspath(path)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f)
    os.replace(tmp, path)
