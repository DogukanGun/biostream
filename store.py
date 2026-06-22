"""
Storage layer: SQLite (data/helio.db) + atomic JSON snapshots (live.json, history.json).
Pure persistence — no auth, no BLE. Shared by the worker (writes) and the gateway (reads paths).
"""
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta

# data-type codes used as sync_state keys (mirror helio.py FT_*); kept local so this
# module stays free of BLE/helio imports (the gateway imports it just for paths).
FT_ACTIVITY = 0x01
FT_PAI = 0x0d
FT_STRESS_AUTO = 0x13
FT_SPO2_NORMAL = 0x25
FT_RESTING_HR = 0x3a
FT_MAX_HR = 0x3d

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LIVE_JSON = os.path.join(DATA_DIR, "live.json")
HISTORY_JSON = os.path.join(DATA_DIR, "history.json")
DB_PATH = os.path.join(DATA_DIR, "helio.db")
HISTORY_MAX = 600
DAYS_BACK = 14                # first-ever sync window (far-past `since` gets rejected; band holds little)


class Store:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.hr_trail = []        # live HR for the 1s chart
        self.latest_steps = None
        self.battery = None
        self.connected = False
        self.db = sqlite3.connect(DB_PATH)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS hr (ts INTEGER PRIMARY KEY, bpm INTEGER);
            CREATE TABLE IF NOT EXISTS battery (ts INTEGER PRIMARY KEY, pct INTEGER);
            CREATE TABLE IF NOT EXISTS activity (ts INTEGER PRIMARY KEY, kind INT, intensity INT,
                steps INT, hr INT, sleep INT, deep_sleep INT, rem_sleep INT);
            CREATE TABLE IF NOT EXISTS resting_hr (ts INTEGER PRIMARY KEY, hr INT, utc_offset INT);
            CREATE TABLE IF NOT EXISTS max_hr (ts INTEGER PRIMARY KEY, hr INT, utc_offset INT);
            CREATE TABLE IF NOT EXISTS spo2 (ts INTEGER PRIMARY KEY, spo2 INT, auto INT);
            CREATE TABLE IF NOT EXISTS stress (ts INTEGER PRIMARY KEY, stress INT, auto INT);
            CREATE TABLE IF NOT EXISTS pai (ts INTEGER PRIMARY KEY, pai_today REAL, pai_total REAL,
                pai_low REAL, pai_moderate REAL, pai_high REAL);
            CREATE TABLE IF NOT EXISTS sync_state (data_type INTEGER PRIMARY KEY, last_ts INTEGER);
        """)
        self.db.commit()

    # -- realtime --
    def add_hr(self, bpm):
        now = int(time.time() * 1000)
        self.hr_trail.append({"t": now, "hr": bpm})
        del self.hr_trail[:-HISTORY_MAX]
        self.db.execute("INSERT OR REPLACE INTO hr VALUES (?,?)", (now, bpm))
        self.db.commit()
        self.write_live()

    def set_steps(self, steps):
        self.latest_steps = steps
        self.write_live()

    def set_battery(self, pct):
        self.battery = pct
        if pct is not None:
            self.db.execute("INSERT OR REPLACE INTO battery VALUES (?,?)", (int(time.time() * 1000), pct))
            self.db.commit()
        self.write_live()

    # -- historical (batched upserts + sync_state bump) --
    def _bump_sync(self, data_type, rows):
        if rows:
            last = max(r["ts"] for r in rows)
            self.db.execute("INSERT OR REPLACE INTO sync_state VALUES (?,?)", (data_type, last))

    def add_activity(self, rows):
        self.db.executemany(
            "INSERT OR REPLACE INTO activity VALUES (:ts,:kind,:intensity,:steps,:hr,:sleep,:deep_sleep,:rem_sleep)", rows)
        self._bump_sync(FT_ACTIVITY, rows)
        self.db.commit()

    def add_resting_hr(self, rows):
        self.db.executemany("INSERT OR REPLACE INTO resting_hr VALUES (:ts,:hr,:utc_offset)", rows)
        self._bump_sync(FT_RESTING_HR, rows)
        self.db.commit()

    def add_max_hr(self, rows):
        self.db.executemany("INSERT OR REPLACE INTO max_hr VALUES (:ts,:hr,:utc_offset)", rows)
        self._bump_sync(FT_MAX_HR, rows)
        self.db.commit()

    def add_spo2(self, rows):
        self.db.executemany("INSERT OR REPLACE INTO spo2 VALUES (:ts,:spo2,:auto)", rows)
        self._bump_sync(FT_SPO2_NORMAL, rows)
        self.db.commit()

    def add_stress(self, rows):
        self.db.executemany("INSERT OR REPLACE INTO stress VALUES (:ts,:stress,:auto)", rows)
        self._bump_sync(FT_STRESS_AUTO, rows)
        self.db.commit()

    def add_pai(self, rows):
        self.db.executemany(
            "INSERT OR REPLACE INTO pai VALUES (:ts,:pai_today,:pai_total,:pai_low,:pai_moderate,:pai_high)", rows)
        self._bump_sync(FT_PAI, rows)
        self.db.commit()

    def since_for(self, data_type):
        row = self.db.execute("SELECT last_ts FROM sync_state WHERE data_type=?", (data_type,)).fetchone()
        if row and row[0]:
            return datetime.fromtimestamp(row[0] / 1000) + timedelta(minutes=1)
        return datetime.now() - timedelta(days=DAYS_BACK)

    # -- snapshots --
    def _today_stats(self):
        c = self.db.cursor()
        midnight = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        steps = c.execute("SELECT COALESCE(SUM(steps),0) FROM activity WHERE ts>=?", (midnight,)).fetchone()[0]
        sleep_min = c.execute(
            "SELECT COUNT(*) FROM activity WHERE ts>=? AND (deep_sleep>0 OR rem_sleep>0)",
            (midnight - 18 * 3600 * 1000,)).fetchone()[0]

        def latest(table, col):
            r = c.execute(f"SELECT {col} FROM {table} ORDER BY ts DESC LIMIT 1").fetchone()
            return r[0] if r else None
        return {
            "steps": self.latest_steps if self.latest_steps is not None else steps,
            "resting_hr": latest("resting_hr", "hr"),
            "spo2": latest("spo2", "spo2"),
            "stress": latest("stress", "stress"),
            "pai_today": latest("pai", "pai_today"),
            "sleep_minutes": sleep_min,
        }

    def write_live(self):
        snap = {
            "updated": int(time.time() * 1000),
            "connected": self.connected,
            "battery": self.battery,
            "hr": self.hr_trail[-1]["hr"] if self.hr_trail else None,
            "steps": self.latest_steps,
            "history": self.hr_trail,
            "today": self._today_stats(),
        }
        self._atomic(LIVE_JSON, snap)

    def write_history(self):
        c = self.db.cursor()
        day_ago = int(time.time() * 1000) - 36 * 3600 * 1000

        def rows(q, args=()):
            return [dict(zip([d[0] for d in c.description], r)) for r in c.execute(q, args).fetchall()]

        activity_recent = rows("SELECT ts, steps, hr FROM activity WHERE ts>=? ORDER BY ts", (day_ago,))
        steps_by_day = rows(
            "SELECT strftime('%Y-%m-%d', ts/1000, 'unixepoch', 'localtime') AS date, "
            "SUM(steps) AS steps FROM activity GROUP BY date ORDER BY date")
        sleep_by_night = rows(
            "SELECT strftime('%Y-%m-%d', ts/1000, 'unixepoch', 'localtime') AS date, "
            "SUM(CASE WHEN deep_sleep>0 OR rem_sleep>0 THEN 1 ELSE 0 END) AS total, "
            "SUM(CASE WHEN deep_sleep>0 THEN 1 ELSE 0 END) AS deep, "
            "SUM(CASE WHEN rem_sleep>0 THEN 1 ELSE 0 END) AS rem "
            "FROM activity GROUP BY date ORDER BY date")
        snap = {
            "updated": int(time.time() * 1000),
            "activity_recent": activity_recent,
            "steps_by_day": steps_by_day,
            "sleep_by_night": sleep_by_night,
            "resting_hr": rows("SELECT ts, hr FROM resting_hr ORDER BY ts"),
            "spo2": rows("SELECT ts, spo2, auto FROM spo2 ORDER BY ts"),
            "stress": rows("SELECT ts, stress FROM stress ORDER BY ts"),
            "pai": rows("SELECT ts, pai_today, pai_total FROM pai ORDER BY ts"),
            "counts": {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                       for t in ("activity", "resting_hr", "max_hr", "spo2", "stress", "pai")},
        }
        self._atomic(HISTORY_JSON, snap)

    @staticmethod
    def _atomic(path, obj):
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
