"""
GraphQL API gateway (open, read-only) over the health data the worker collects.

Reads data/helio.db (read-only) + data/*.json — never writes, never touches BLE/secrets.
Run:  uvicorn api:app --host 127.0.0.1 --port 8000   ->  GraphiQL at http://localhost:8000/graphql

Query everything; time-series take start/end (epoch ms) + limit (default 500, max 50000).
"""
import asyncio
import json
import os
import sqlite3
from typing import AsyncGenerator, List, NewType, Optional

import strawberry
from strawberry.scalars import JSON
from strawberry.fastapi import GraphQLRouter
from fastapi import FastAPI

import contextlib
from contextlib import asynccontextmanager

_CURRENT = None     # the active Config; set by create_app(), read by the resolvers

DEFAULT_LIMIT = 500
MAX_LIMIT = 50000

# epoch-ms timestamps exceed GraphQL's 32-bit Int -> custom 64-bit scalar
BigInt = strawberry.scalar(
    NewType("BigInt", int),
    serialize=lambda v: None if v is None else int(v),
    parse_value=lambda v: int(v),
    description="64-bit integer (e.g. epoch milliseconds)",
)


# ---- read-only data access -------------------------------------------------
def _db():
    con = sqlite3.connect(f"file:{_CURRENT.db_path}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def _json_file(name):
    try:
        with open(os.fspath(_CURRENT.data_dir / f"{name}.json")) as f:
            return json.load(f)
    except Exception:
        return {}


def _series(table, cols, start=None, end=None, limit=None, order="DESC"):
    lim = min(limit or DEFAULT_LIMIT, MAX_LIMIT)
    where, args = [], []
    if start is not None:
        where.append("ts >= ?"); args.append(start)
    if end is not None:
        where.append("ts <= ?"); args.append(end)
    sql = f"SELECT ts,{','.join(cols)} FROM {table}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY ts {order} LIMIT ?"
    args.append(lim)
    con = _db()
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def _mk(cls, d):
    d = d or {}
    return cls(**{k: d.get(k) for k in cls.__annotations__})


# ---- types: strap time-series (helio.db) -----------------------------------
@strawberry.type
class HrPoint:
    ts: BigInt
    bpm: Optional[int]


@strawberry.type
class ActivityPoint:
    ts: BigInt
    kind: Optional[int]
    intensity: Optional[int]
    steps: Optional[int]
    hr: Optional[int]
    sleep: Optional[int]
    deep_sleep: Optional[int]
    rem_sleep: Optional[int]


@strawberry.type
class StressPoint:
    ts: BigInt
    stress: Optional[int]
    auto: Optional[int]


@strawberry.type
class HrSample:
    ts: BigInt
    hr: Optional[int]
    utc_offset: Optional[int]


@strawberry.type
class Spo2Point:
    ts: BigInt
    spo2: Optional[int]
    auto: Optional[int]


@strawberry.type
class PaiPoint:
    ts: BigInt
    pai_today: Optional[float]
    pai_total: Optional[float]
    pai_low: Optional[float]
    pai_moderate: Optional[float]
    pai_high: Optional[float]


@strawberry.type
class BatteryPoint:
    ts: BigInt
    pct: Optional[int]


# ---- types: live (live.json) -----------------------------------------------
@strawberry.type
class TodayStats:
    steps: Optional[int]
    resting_hr: Optional[int]
    spo2: Optional[int]
    stress: Optional[int]
    pai_today: Optional[float]
    sleep_minutes: Optional[int]


@strawberry.type
class Live:
    updated: Optional[BigInt]
    connected: bool
    battery: Optional[int]
    hr: Optional[int]
    steps: Optional[int]
    today: Optional[TodayStats]
    history: List[HrPoint]


# ---- types: oura (oura.json) -----------------------------------------------
@strawberry.type
class OuraNight:
    day: Optional[str]
    total_h: Optional[float]
    deep_h: Optional[float]
    rem_h: Optional[float]
    light_h: Optional[float]
    hrv: Optional[int]
    resting_hr: Optional[int]
    avg_hr: Optional[int]
    spo2: Optional[float]
    efficiency: Optional[int]
    bedtime_start: Optional[str]
    time_in_bed_h: Optional[float]


@strawberry.type
class DayScore:
    day: Optional[str]
    score: Optional[int]


@strawberry.type
class DaySpo2:
    day: Optional[str]
    spo2: Optional[float]


@strawberry.type
class DayActivity:
    day: Optional[str]
    steps: Optional[int]
    active_cal: Optional[int]


@strawberry.type
class OuraHrPoint:
    t: Optional[BigInt]
    bpm: Optional[int]
    source: Optional[str]


@strawberry.type
class Oura:
    updated: Optional[BigInt]
    nights: List[OuraNight]
    readiness: List[DayScore]
    sleep_score: List[DayScore]
    daily_spo2: List[DaySpo2]
    daily_activity: List[DayActivity]
    intraday_hr: List[OuraHrPoint]


# ---- types: insights (insights.json) — nested stats as JSON scalars --------
@strawberry.type
class Insights:
    updated: Optional[BigInt]
    window_days: Optional[int]
    n_nights: Optional[int]
    caveats: Optional[JSON]
    recovery: Optional[JSON]
    derived: Optional[JSON]
    correlations: Optional[JSON]
    trends: Optional[JSON]
    intraday: Optional[JSON]
    findings: Optional[JSON]


# ---- query root (thin resolvers; worker already computed everything) --------
@strawberry.type
class Query:
    @strawberry.field
    def live(self) -> Live:
        d = _json_file("live")
        t = d.get("today")
        return Live(
            updated=d.get("updated"), connected=bool(d.get("connected")),
            battery=d.get("battery"), hr=d.get("hr"), steps=d.get("steps"),
            today=_mk(TodayStats, t) if t else None,
            history=[HrPoint(ts=p.get("t"), bpm=p.get("hr")) for p in d.get("history", [])],
        )

    @strawberry.field
    def heart_rate(self, start: Optional[BigInt] = None, end: Optional[BigInt] = None,
                   limit: Optional[int] = None) -> List[HrPoint]:
        return [_mk(HrPoint, r) for r in _series("hr", ["bpm"], start, end, limit)]

    @strawberry.field
    def activity(self, start: Optional[BigInt] = None, end: Optional[BigInt] = None,
                 limit: Optional[int] = None) -> List[ActivityPoint]:
        cols = ["kind", "intensity", "steps", "hr", "sleep", "deep_sleep", "rem_sleep"]
        return [_mk(ActivityPoint, r) for r in _series("activity", cols, start, end, limit)]

    @strawberry.field
    def stress(self, start: Optional[BigInt] = None, end: Optional[BigInt] = None,
               limit: Optional[int] = None) -> List[StressPoint]:
        return [_mk(StressPoint, r) for r in _series("stress", ["stress", "auto"], start, end, limit)]

    @strawberry.field
    def resting_hr(self, start: Optional[BigInt] = None, end: Optional[BigInt] = None,
                   limit: Optional[int] = None) -> List[HrSample]:
        return [_mk(HrSample, r) for r in _series("resting_hr", ["hr", "utc_offset"], start, end, limit)]

    @strawberry.field
    def max_hr(self, start: Optional[BigInt] = None, end: Optional[BigInt] = None,
               limit: Optional[int] = None) -> List[HrSample]:
        return [_mk(HrSample, r) for r in _series("max_hr", ["hr", "utc_offset"], start, end, limit)]

    @strawberry.field
    def spo2(self, start: Optional[BigInt] = None, end: Optional[BigInt] = None,
             limit: Optional[int] = None) -> List[Spo2Point]:
        return [_mk(Spo2Point, r) for r in _series("spo2", ["spo2", "auto"], start, end, limit)]

    @strawberry.field
    def pai(self, start: Optional[BigInt] = None, end: Optional[BigInt] = None,
            limit: Optional[int] = None) -> List[PaiPoint]:
        cols = ["pai_today", "pai_total", "pai_low", "pai_moderate", "pai_high"]
        return [_mk(PaiPoint, r) for r in _series("pai", cols, start, end, limit)]

    @strawberry.field
    def battery(self, start: Optional[BigInt] = None, end: Optional[BigInt] = None,
                limit: Optional[int] = None) -> List[BatteryPoint]:
        return [_mk(BatteryPoint, r) for r in _series("battery", ["pct"], start, end, limit)]

    @strawberry.field
    def oura(self) -> Oura:
        d = _json_file("oura")
        return Oura(
            updated=d.get("updated"),
            nights=[_mk(OuraNight, n) for n in d.get("nights", [])],
            readiness=[_mk(DayScore, x) for x in d.get("readiness", [])],
            sleep_score=[_mk(DayScore, x) for x in d.get("sleep_score", [])],
            daily_spo2=[_mk(DaySpo2, x) for x in d.get("spo2", [])],
            daily_activity=[_mk(DayActivity, x) for x in d.get("activity", [])],
            intraday_hr=[_mk(OuraHrPoint, x) for x in d.get("heartrate", [])],
        )

    @strawberry.field
    def insights(self) -> Insights:
        d = _json_file("insights")
        return Insights(
            updated=d.get("updated"), window_days=d.get("window_days"), n_nights=d.get("n_nights"),
            caveats=d.get("caveats"), recovery=d.get("recovery"), derived=d.get("derived"),
            correlations=d.get("correlations"), trends=d.get("trends"), intraday=d.get("intraday"),
            findings=d.get("insights"),
        )


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def heart_rate_live(self) -> AsyncGenerator[HrPoint, None]:
        """Push each new HR beat as the worker writes it (tails helio.db, read-only)."""
        con = _db()
        try:
            r = con.execute("SELECT MAX(ts) AS m FROM hr").fetchone()
            last = r["m"] or 0
        finally:
            con.close()
        while True:
            await asyncio.sleep(1.0)
            con = _db()
            try:
                rows = con.execute("SELECT ts,bpm FROM hr WHERE ts>? ORDER BY ts", (last,)).fetchall()
            finally:
                con.close()
            for row in rows:
                last = row["ts"]
                yield HrPoint(ts=row["ts"], bpm=row["bpm"])


def create_app(config, *, run_worker=False):
    """Build the FastAPI app bound to `config`. With run_worker=True the collector runs as a
    lifespan background task in the SAME process (one call serves both collection + GraphQL)."""
    global _CURRENT
    _CURRENT = config
    schema = strawberry.Schema(query=Query, subscription=Subscription)
    graphql_app = GraphQLRouter(schema, graphql_ide="graphiql")

    @asynccontextmanager
    async def lifespan(app):
        task = None
        if run_worker:
            from .worker import run_worker as _rw
            task = asyncio.create_task(_rw(config))
        try:
            yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="biostream gateway (open, read-only)", lifespan=lifespan)
    app.include_router(graphql_app, prefix="/graphql")
    app.get("/")(lambda: {"service": "biostream", "graphql": "/graphql"})
    return app
