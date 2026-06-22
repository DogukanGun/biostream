"""
Health-data analytics -> data/insights.json

Computes (all single-subject, n=1, honestly hedged):
  - FDR-corrected correlations (Pearson + Spearman) across Oura nightly metrics
  - OLS trends + 7-night baselines for HRV and resting HR
  - a personal Recovery Score (0-100), validated against Oura's own readiness
  - derived metrics (HRV baseline deviation, RHR trend, sleep consistency)
  - intraday from the strap (circadian HR, HR zones, stress-vs-HR)
  - ranked plain-language insights with strength gating

Standalone:  python3 analyze.py     From the collector:  analyze.refresh()
"""
import itertools
import json
import math
import os
import sqlite3
import time
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.stats import linregress, pearsonr, spearmanr

WINDOW_DAYS = 30
ROLL = 7
MIN_N = 8
MIN_SLEEP_H = 3.0   # below this isn't a real night (nap / partial sync) -> excluded
CORR_VARS = ["hrv", "resting_hr", "total_h", "deep_h", "rem_h", "efficiency",
             "readiness", "sleep_score", "steps"]
# facets of the same sleep: correlations among these are structural/trivial, not insights
SLEEP_FACETS = {"total_h", "deep_h", "rem_h", "light_h", "efficiency", "sleep_score"}
NICE = {"hrv": "HRV", "resting_hr": "resting HR", "total_h": "sleep duration",
        "deep_h": "deep sleep", "rem_h": "REM sleep", "efficiency": "sleep efficiency",
        "readiness": "readiness", "sleep_score": "sleep score", "steps": "steps"}


# ---- load -------------------------------------------------------------------
def load_oura_nights(oura_json):
    try:
        with open(oura_json) as f:
            o = json.load(f)
    except Exception:
        return pd.DataFrame()
    nights = o.get("nights", [])
    if not nights:
        return pd.DataFrame()
    df = pd.DataFrame(nights)
    if "day" not in df or "total_h" not in df:
        return pd.DataFrame()
    df["total_h"] = pd.to_numeric(df["total_h"], errors="coerce")
    df = df[df["total_h"] >= MIN_SLEEP_H]   # drop naps / partial syncs (not real nights)
    if df.empty:
        return pd.DataFrame()
    # one row per day: keep the longest sleep
    df = df.sort_values("total_h").groupby("day", as_index=False).tail(1)
    df["day"] = pd.to_datetime(df["day"])
    df = df.set_index("day").sort_index()
    for c in ["total_h", "deep_h", "rem_h", "light_h", "hrv", "resting_hr", "avg_hr", "efficiency"]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    def joined(arr, key):
        if not arr:
            return np.nan
        d = pd.DataFrame(arr)
        if "day" not in d or key not in d:
            return np.nan
        d["day"] = pd.to_datetime(d["day"])
        return pd.to_numeric(d.set_index("day")[key], errors="coerce")

    df["readiness"] = joined(o.get("readiness", []), "score")
    df["sleep_score"] = joined(o.get("sleep_score", []), "score")
    df["steps"] = joined(o.get("activity", []), "steps")
    return df


# ---- correlations -----------------------------------------------------------
def _bh_fdr(pvals, alpha=0.05):
    """Benjamini-Hochberg FDR. Returns (reject_array, p_adjusted_array)."""
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order] * n / np.arange(1, n + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]  # enforce monotonicity
    adj = np.clip(ranked, 0, 1)
    out = np.empty(n)
    out[order] = adj
    return out < alpha, out


def correlations(df):
    if df.empty:
        return []
    out, pvals = [], []
    for a, b in itertools.combinations(CORR_VARS, 2):
        if a not in df or b not in df:
            continue
        sub = df[[a, b]].dropna()
        n = len(sub)
        if n < 4 or sub[a].std(ddof=1) == 0 or sub[b].std(ddof=1) == 0:
            continue
        pr, pp = pearsonr(sub[a], sub[b])
        sr, sp = spearmanr(sub[a], sub[b])
        out.append({"a": a, "b": b, "pearson_r": round(float(pr), 3), "pearson_p": round(float(pp), 4),
                    "spearman_r": round(float(sr), 3), "spearman_p": round(float(sp), 4),
                    "n": int(n), "low_n": bool(n < MIN_N),
                    "trivial": bool(a in SLEEP_FACETS and b in SLEEP_FACETS)})
        pvals.append(pp)
    if pvals:
        rej, p_fdr = _bh_fdr(pvals)
        for o_, pf, r_ in zip(out, p_fdr, rej):
            o_["p_fdr"] = round(float(pf), 4)
            o_["significant_fdr"] = bool(r_)
    out.sort(key=lambda x: abs(x["pearson_r"]), reverse=True)
    return out


# ---- trends -----------------------------------------------------------------
def _trend_one(df, col):
    if col not in df:
        return None
    s = df[col].dropna()
    n = len(s)
    if n < 4:
        return None
    days = np.asarray((s.index - s.index[0]).days, dtype=float)
    if days.std() == 0:
        return None
    lr = linregress(days, s.values)
    slope, p, r2 = float(lr.slope), float(lr.pvalue), float(lr.rvalue ** 2)
    direction = "flat" if (math.isnan(p) or p >= 0.05) else ("rising" if slope > 0 else "falling")
    return {"slope_per_week": round(slope * 7, 3), "p": round(p, 4), "r2": round(r2, 3),
            "n": int(n), "direction": direction}


def trends(df):
    out = {}
    for col in ("hrv", "resting_hr"):
        t = _trend_one(df, col)
        if t is None:
            out[col] = {"slope_per_week": None, "p": None, "r2": None,
                        "n": int(df[col].notna().sum()) if col in df else 0,
                        "direction": "n/a", "series": []}
            continue
        base = df[col].rolling(ROLL, min_periods=3).mean()
        t["series"] = [{"day": d.strftime("%m-%d"),
                        "value": (None if pd.isna(v) else round(float(v), 1)),
                        "baseline": (None if pd.isna(bv) else round(float(bv), 1))}
                       for d, v, bv in zip(df.index, df[col], base)]
        out[col] = t
    return out


# ---- recovery score ---------------------------------------------------------
def _z(s):
    s = pd.to_numeric(s, errors="coerce")
    sd = s.std(ddof=0)
    if not sd or pd.isna(sd):
        return pd.Series(np.nan, index=s.index)
    return (s - s.mean()) / sd


def recovery_score(df):
    empty = {"today": None, "trend": [],
             "validation": {"pearson_r": None, "p": None, "spearman_r": None, "n": 0,
                            "verdict": "insufficient data"}}
    if df.empty:
        return empty
    comps = []
    if "hrv" in df:
        comps.append(_z(df["hrv"]))
    if "resting_hr" in df:
        comps.append(-_z(df["resting_hr"]))
    if "deep_h" in df and "rem_h" in df:
        comps.append(_z(df["deep_h"] + df["rem_h"]))
    if "efficiency" in df:
        comps.append(_z(df["efficiency"]))
    if not comps:
        return empty
    Z = pd.concat(comps, axis=1).mean(axis=1, skipna=True)
    score = 100 / (1 + np.exp(-Z))
    trend = [{"day": d.strftime("%m-%d"), "score": (None if pd.isna(v) else int(round(v)))}
             for d, v in zip(df.index, score)]
    sc = score.dropna()
    today = int(round(sc.iloc[-1])) if len(sc) else None

    val_df = pd.DataFrame({"score": score, "readiness": df.get("readiness")}).dropna()
    validation = empty["validation"]
    if len(val_df) >= 4 and val_df["score"].std() > 0 and val_df["readiness"].std() > 0:
        pr, pp = pearsonr(val_df["score"], val_df["readiness"])
        sr, _ = spearmanr(val_df["score"], val_df["readiness"])
        verdict = ("tracks Oura readiness" if pr >= 0.4 else
                   "loosely tracks Oura readiness" if pr >= 0.2 else
                   "diverges from Oura readiness (experimental)")
        validation = {"pearson_r": round(float(pr), 3), "p": round(float(pp), 4),
                      "spearman_r": round(float(sr), 3), "n": int(len(val_df)), "verdict": verdict}
    return {"today": today, "trend": trend, "validation": validation}


# ---- derived ----------------------------------------------------------------
def derived(df, trends_out):
    dev = {"value_sd": None, "today": None, "baseline_mean": None, "baseline_sd": None,
           "label": "n/a", "n": 0}
    if not df.empty and "hrv" in df:
        hrv = df["hrv"].dropna()
        if len(hrv) >= 4:
            today = float(hrv.iloc[-1])
            base = hrv.iloc[-(ROLL + 1):-1]
            if len(base) >= 3 and base.std(ddof=0) > 0:
                z = (today - base.mean()) / base.std(ddof=0)
                label = "strained" if z < -1 else ("primed" if z > 1 else "balanced")
                dev = {"value_sd": round(float(z), 2), "today": round(today, 1),
                       "baseline_mean": round(float(base.mean()), 1),
                       "baseline_sd": round(float(base.std(ddof=0)), 1), "label": label,
                       "n": int(len(base))}
    th = pd.to_numeric(df["total_h"], errors="coerce").dropna() if "total_h" in df else pd.Series(dtype=float)
    consistency = {"total_h_sd": (round(float(th.std(ddof=0)), 2) if len(th) >= 3 else None),
                   "bedtime_sd_min": None, "bedtime_available": False}
    if "bedtime_start" in df.columns:
        bt = pd.to_datetime(df["bedtime_start"], errors="coerce", utc=True).dropna()
        if len(bt) >= 3:
            # minutes-of-day anchored away from midnight to avoid wrap
            mins = (bt.dt.hour * 60 + bt.dt.minute).astype(float)
            mins = mins.apply(lambda m: m + 1440 if m < 720 else m)  # shift early-AM past midnight
            consistency["bedtime_sd_min"] = round(float(mins.std(ddof=0)), 1)
        consistency["bedtime_available"] = True
    return {"hrv_baseline_deviation": dev,
            "rhr_trend_bpm_per_week": trends_out.get("resting_hr", {}).get("slope_per_week"),
            "sleep_consistency": consistency}


# ---- intraday (strap) -------------------------------------------------------
def intraday(db_path):
    res = {"available": False, "hours_covered": 0, "max_hr_method": None, "max_hr": None,
           "circadian": [], "zones": [], "stress_vs_hr": None}
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except Exception:
        return res
    try:
        hr = pd.read_sql_query("SELECT ts, bpm FROM hr WHERE bpm>0 AND bpm<255 ORDER BY ts", con)
        if len(hr) < 60:
            return res
        local_tz = datetime.now().astimezone().tzinfo
        local = pd.to_datetime(hr["ts"], unit="ms", utc=True).dt.tz_convert(local_tz)
        hr["hour"] = local.dt.hour
        circ = hr.groupby("hour")["bpm"].agg(["mean", "count"]).reset_index()
        res["circadian"] = [{"hour": int(r["hour"]), "mean_hr": round(float(r["mean"]), 1),
                             "n": int(r["count"])} for _, r in circ.iterrows()]
        res["hours_covered"] = int(hr["hour"].nunique())

        max_hr = float(hr["bpm"].quantile(0.99))
        res["max_hr"], res["max_hr_method"] = round(max_hr, 0), "percentile_p99"
        bounds = [0.0, 0.6, 0.7, 0.8, 0.9, 1.01]
        labels = ["rest / very light", "light", "moderate", "hard", "max"]
        total = len(hr)
        res["zones"] = [{"zone": i + 1, "label": labels[i],
                         "pct_time": round(100 * float(((hr["bpm"] >= bounds[i] * max_hr) &
                                                        (hr["bpm"] < bounds[i + 1] * max_hr)).sum()) / total, 1)}
                        for i in range(5)]

        stress = pd.read_sql_query("SELECT ts, stress FROM stress ORDER BY ts", con)
        if len(stress) >= 10:
            s = stress.assign(dt=pd.to_datetime(stress["ts"], unit="ms")).sort_values("dt")
            h = hr.assign(dt=pd.to_datetime(hr["ts"], unit="ms")).sort_values("dt")
            m = pd.merge_asof(s, h[["dt", "bpm"]], on="dt", direction="nearest",
                              tolerance=pd.Timedelta("5min")).dropna(subset=["bpm"])
            if len(m) >= 8 and m["stress"].std() > 0 and m["bpm"].std() > 0:
                pr, pp = pearsonr(m["stress"], m["bpm"])
                samp = m.sample(min(200, len(m)), random_state=0)
                res["stress_vs_hr"] = {"pearson_r": round(float(pr), 3), "p": round(float(pp), 4),
                                       "n": int(len(m)),
                                       "scatter": [{"stress": int(r.stress), "hr": int(r.bpm)}
                                                   for r in samp.itertuples()]}
        res["available"] = len(res["circadian"]) > 0
    except Exception as e:
        print(f"[analyze] intraday skipped: {e}")
    finally:
        con.close()
    return res


# ---- insights ---------------------------------------------------------------
def _strength(r, n, sig):
    ar = abs(r) if r is not None else 0
    if ar >= 0.5 and n >= 15 and sig:
        return "strong"
    if ar >= 0.3 and n >= 10:
        return "moderate"
    return "exploratory"


def insights_text(corr, tr, rec, der, intr):
    items = []
    interesting = [c for c in corr if not c.get("trivial")]
    for c in interesting[:6]:
        sign = "positively" if c["pearson_r"] > 0 else "negatively"
        items.append({
            "text": f"{NICE.get(c['a'], c['a'])} and {NICE.get(c['b'], c['b'])} move together "
                    f"{sign} (r={c['pearson_r']:+.2f}, n={c['n']}).",
            "strength": _strength(c["pearson_r"], c["n"], c.get("significant_fdr", False)),
            "evidence": {"r": c["pearson_r"], "p": c["pearson_p"], "n": c["n"]},
            "hedge": "Association, not proof of cause." + (" Small sample." if c["low_n"] else "")})
    v = rec.get("validation", {})
    if v.get("n"):
        items.append({
            "text": f"Your Recovery Score {v['verdict']} (r={v['pearson_r']:+.2f}, n={v['n']}).",
            "strength": _strength(v["pearson_r"], v["n"], v.get("p") is not None and v["p"] < 0.05),
            "evidence": {"r": v["pearson_r"], "p": v["p"], "n": v["n"]},
            "hedge": "Self-check of a DIY metric vs Oura's own score."})
    for col, unit, name in (("resting_hr", "bpm", "Resting HR"), ("hrv", "ms", "HRV")):
        t = tr.get(col, {})
        if t.get("direction") in ("rising", "falling"):
            items.append({
                "text": f"{name} is trending {t['direction']} ({t['slope_per_week']:+.1f} {unit}/week, n={t['n']}).",
                "strength": "moderate" if (t["p"] and t["p"] < 0.05 and t["n"] >= 10) else "exploratory",
                "evidence": {"r": t.get("r2"), "p": t["p"], "n": t["n"]},
                "hedge": "Short window; trend may not persist."})
    d = der.get("hrv_baseline_deviation", {})
    if d.get("value_sd") is not None:
        items.append({
            "text": f"Today's HRV is {d['value_sd']:+.1f} SD vs your 7-night baseline — {d['label']}.",
            "strength": "exploratory", "evidence": {"r": None, "p": None, "n": d["n"]},
            "hedge": "Single-day snapshot."})
    sh = intr.get("stress_vs_hr")
    if sh:
        items.append({
            "text": f"Higher stress readings track {'higher' if sh['pearson_r'] > 0 else 'lower'} "
                    f"heart rate (r={sh['pearson_r']:+.2f}, n={sh['n']}).",
            "strength": _strength(sh["pearson_r"], sh["n"], sh["p"] < 0.05),
            "evidence": {"r": sh["pearson_r"], "p": sh["p"], "n": sh["n"]},
            "hedge": "Within-day, same device."})
    order = {"strong": 0, "moderate": 1, "exploratory": 2}
    items.sort(key=lambda x: (order[x["strength"]],
                              -(abs(x["evidence"]["r"]) if x["evidence"]["r"] is not None else 0)))
    for i, it in enumerate(items):
        it["rank"] = i + 1
    return items


# ---- assemble / io ----------------------------------------------------------
def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        v = float(o)
        return None if math.isnan(v) else v
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, float):
        return None if math.isnan(o) else o
    return o


def compute(config):
    df = load_oura_nights(config.oura_json)
    n = int(len(df))
    tr = trends(df)
    rec = recovery_score(df)
    der = derived(df, tr)
    corr = correlations(df)
    intr = intraday(config.db_path)
    ins = insights_text(corr, tr, rec, der, intr)
    return {
        "updated": int(time.time() * 1000),
        "window_days": WINDOW_DAYS,
        "n_nights": n,
        "caveats": {"subject_n": 1,
                    "multiple_comparisons": "Pearson p-values FDR-adjusted (Benjamini-Hochberg)",
                    "note": "Single subject (n=1); small samples; associations are not proof of cause."},
        "recovery": rec,
        "derived": der,
        "correlations": corr,
        "trends": tr,
        "intraday": intr,
        "insights": ins,
    }


def _write(obj, path):
    path = os.fspath(path)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_clean(obj), f)
    os.replace(tmp, path)


def refresh(config):
    try:
        out = compute(config)
    except Exception as e:
        print(f"[analyze] compute failed: {e}")
        return None
    _write(out, config.insights_json)
    return out


def main():
    from .config import Config
    out = refresh(Config.from_env())
    if not out:
        return
    print(f"insights -> {out['n_nights']} nights, {len(out['correlations'])} correlations, "
          f"{len(out['insights'])} insights")
    rec = out["recovery"]
    print(f"  Recovery Score today: {rec['today']}  (validation vs readiness: "
          f"r={rec['validation']['pearson_r']}, n={rec['validation']['n']})")
    if out["correlations"]:
        c = out["correlations"][0]
        print(f"  top correlation: {c['a']}~{c['b']}  r={c['pearson_r']} p_fdr={c.get('p_fdr')} n={c['n']}")
    for it in out["insights"][:5]:
        print(f"  [{it['strength']:11}] {it['text']}")


if __name__ == "__main__":
    main()
