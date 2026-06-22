"use client";

import { useEffect, useState, type ReactNode } from "react";
import {
  LineChart, Line, BarChart, Bar, AreaChart, Area, ScatterChart, Scatter, Cell,
  XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer,
} from "recharts";

type Today = {
  steps: number | null; resting_hr: number | null; spo2: number | null;
  stress: number | null; pai_today: number | null; sleep_minutes: number | null;
};
type Live = {
  updated: number | null; connected: boolean; battery: number | null;
  hr: number | null; steps: number | null;
  history: { t: number; hr: number }[]; today?: Today;
};
type Hist = {
  activity_recent: { ts: number; steps: number; hr: number }[];
  steps_by_day: { date: string; steps: number }[];
  sleep_by_night: { date: string; total: number; deep: number; rem: number }[];
  resting_hr: { ts: number; hr: number }[];
  spo2: { ts: number; spo2: number }[];
  stress: { ts: number; stress: number }[];
  pai: { ts: number; pai_today: number }[];
  counts: Record<string, number>;
};
type OuraNight = {
  day: string; total_h: number; deep_h: number; rem_h: number; light_h: number;
  hrv: number | null; resting_hr: number | null; avg_hr: number | null;
  spo2: number | null; efficiency: number | null;
};
type Oura = {
  updated: number | null;
  nights: OuraNight[];
  readiness: { day: string; score: number | null }[];
  sleep_score: { day: string; score: number | null }[];
  spo2: { day: string; spo2: number | null }[];
  activity: { day: string; steps: number | null }[];
  heartrate: { t: number; bpm: number; source: string }[];
};
type Corr = { a: string; b: string; pearson_r: number; pearson_p: number; n: number; low_n: boolean; trivial: boolean; significant_fdr?: boolean };
type Insight = { rank: number; text: string; strength: "strong" | "moderate" | "exploratory"; evidence: { r: number | null; p: number | null; n: number }; hedge: string };
type TrendSeries = { slope_per_week: number | null; p: number | null; direction: string; series: { day: string; value: number | null; baseline: number | null }[] };
type Insights = {
  updated: number | null;
  n_nights: number;
  recovery: { today: number | null; trend: { day: string; score: number | null }[]; validation: { pearson_r: number | null; n: number; verdict: string } };
  derived: { hrv_baseline_deviation: { value_sd: number | null; label: string; n?: number }; rhr_trend_bpm_per_week: number | null; sleep_consistency: { total_h_sd?: number | null; bedtime_sd_min?: number | null } };
  correlations: Corr[];
  trends: { hrv?: TrendSeries; resting_hr?: TrendSeries };
  intraday: { available: boolean; max_hr?: number | null; circadian: { hour: number; mean_hr: number; n: number }[]; zones: { zone: number; label: string; pct_time: number }[]; stress_vs_hr: { pearson_r: number; p: number; n: number; scatter: { stress: number; hr: number }[] } | null };
  insights: Insight[];
};

const hm = (ms: number) =>
  new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const md = (d: string) => d.slice(5);

const TT = {
  contentStyle: { background: "#0a0a0a", border: "1px solid #262626", borderRadius: 8 },
  labelStyle: { color: "#a3a3a3" },
};

export default function Home() {
  const [live, setLive] = useState<Live | null>(null);
  const [hist, setHist] = useState<Hist | null>(null);
  const [oura, setOura] = useState<Oura | null>(null);
  const [ins, setIns] = useState<Insights | null>(null);

  useEffect(() => {
    let on = true;
    const pull = async (url: string, set: (v: unknown) => void) => {
      try {
        const r = await fetch(url, { cache: "no-store" });
        const j = await r.json();
        if (on) set(j);
      } catch {}
    };
    pull("/api/live", setLive as (v: unknown) => void);
    pull("/api/history", setHist as (v: unknown) => void);
    pull("/api/oura", setOura as (v: unknown) => void);
    pull("/api/insights", setIns as (v: unknown) => void);
    const a = setInterval(() => pull("/api/live", setLive as (v: unknown) => void), 1000);
    const b = setInterval(() => pull("/api/history", setHist as (v: unknown) => void), 30000);
    const c = setInterval(() => pull("/api/oura", setOura as (v: unknown) => void), 30000);
    const d = setInterval(() => pull("/api/insights", setIns as (v: unknown) => void), 30000);
    return () => { on = false; clearInterval(a); clearInterval(b); clearInterval(c); clearInterval(d); };
  }, []);

  const t = live?.today;
  const connected = live?.connected ?? false;
  const hrTrail = (live?.history ?? []).map((s) => ({ time: hm(s.t), hr: s.hr }));
  const actHr = (hist?.activity_recent ?? []).filter((s) => s.hr > 0 && s.hr < 255)
    .map((s) => ({ time: hm(s.ts), hr: s.hr }));
  const stress = (hist?.stress ?? []).map((s) => ({ time: hm(s.ts), stress: s.stress }));
  const rhr = (hist?.resting_hr ?? []).map((s) => ({ time: hm(s.ts), hr: s.hr }));
  const spo2 = (hist?.spo2 ?? []).map((s) => ({ time: hm(s.ts), spo2: s.spo2 }));
  const stepsDay = (hist?.steps_by_day ?? []).map((s) => ({ date: md(s.date), steps: s.steps }));

  const nights = oura?.nights ?? [];
  const lastNight = nights[nights.length - 1];
  const hrvSeries = nights.filter((n) => n.hrv != null).map((n) => ({ day: md(n.day), hrv: n.hrv }));
  const sleepStages = nights.map((n) => ({ day: md(n.day), deep: n.deep_h, rem: n.rem_h, light: n.light_h }));
  const readiness = (oura?.readiness ?? []).filter((r) => r.score != null);
  const ouraHr = (oura?.heartrate ?? []).map((h) => ({ time: hm(h.t), bpm: h.bpm }));

  const nice: Record<string, string> = { hrv: "HRV", resting_hr: "resting HR", total_h: "sleep", deep_h: "deep sleep", rem_h: "REM", light_h: "light sleep", efficiency: "efficiency", readiness: "readiness", sleep_score: "sleep score", steps: "steps" };
  const rec = ins?.recovery;
  const hrvDev = ins?.derived?.hrv_baseline_deviation;
  const rhrTrend = ins?.derived?.rhr_trend_bpm_per_week ?? null;
  const recColor = rec?.today == null ? "text-neutral-400" : rec.today >= 60 ? "text-emerald-400" : rec.today >= 40 ? "text-amber-400" : "text-rose-400";
  const corrBars = (ins?.correlations ?? []).filter((c) => !c.trivial).slice(0, 10).map((c) => ({ name: `${nice[c.a] || c.a} ↔ ${nice[c.b] || c.b}`, r: c.pearson_r, sig: c.significant_fdr ?? false }));
  const hrvTrend = ins?.trends?.hrv?.series ?? [];
  const circadian = (ins?.intraday?.circadian ?? []).map((c) => ({ hour: c.hour, hr: c.mean_hr }));
  const zones = ins?.intraday?.zones ?? [];
  const stressVsHr = ins?.intraday?.stress_vs_hr ?? null;
  const stressScatter = stressVsHr?.scatter ?? [];

  return (
    <main className="min-h-screen w-full bg-neutral-950 text-neutral-100 p-5 md:p-8">
      <div className="mx-auto max-w-5xl">
        <header className="mb-7 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Amazfit Helio Strap</h1>
            <p className="text-sm text-neutral-400">All data · reverse-engineered over BLE</p>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <span className={`h-2.5 w-2.5 rounded-full ${connected ? "bg-emerald-400 animate-pulse" : "bg-neutral-600"}`} />
            <span className="text-neutral-300">{connected ? "Connected" : "Disconnected"}</span>
          </div>
        </header>

        {/* primary live vitals */}
        <section className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Heart rate" value={live?.hr ?? "—"} unit="bpm" color="text-rose-400" big />
          <Stat label="Steps today" value={t?.steps ?? live?.steps ?? "—"} unit="" color="text-sky-400" big />
          <Stat label="Battery" value={live?.battery ?? "—"} unit="%" color="text-emerald-400" big />
          <Stat label="Sleep" value={t?.sleep_minutes ? Math.round((t.sleep_minutes / 60) * 10) / 10 : "—"} unit="h" color="text-indigo-400" big />
        </section>

        {/* secondary metrics */}
        <section className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Resting HR" value={t?.resting_hr ?? "—"} unit="bpm" color="text-violet-300" />
          <Stat label="SpO₂" value={t?.spo2 ?? "—"} unit="%" color="text-cyan-300" />
          <Stat label="Stress" value={t?.stress ?? "—"} unit="" color="text-amber-300" />
          <Stat label="PAI today" value={t?.pai_today != null ? Math.round(t.pai_today) : "—"} unit="" color="text-emerald-300" />
        </section>

        {/* live HR */}
        <Card title="Heart rate · live">
          <Chart has={hrTrail.length > 1} empty="waiting for live beats…">
            <LineChart data={hrTrail} margin={{ top: 6, right: 10, bottom: 0, left: -14 }}>
              <CartesianGrid stroke="#262626" vertical={false} />
              <XAxis dataKey="time" tick={{ fill: "#737373", fontSize: 11 }} minTickGap={48} />
              <YAxis domain={[(v: number) => Math.floor(v - 5), (v: number) => Math.ceil(v + 5)]} tick={{ fill: "#737373", fontSize: 11 }} width={34} allowDecimals={false} />
              <Tooltip {...TT} itemStyle={{ color: "#fb7185" }} />
              <Line type="monotone" dataKey="hr" stroke="#fb7185" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </Chart>
        </Card>

        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card title="Steps per day">
            <Chart has={stepsDay.length > 0} empty="no daily steps yet">
              <BarChart data={stepsDay} margin={{ top: 6, right: 10, bottom: 0, left: -14 }}>
                <CartesianGrid stroke="#262626" vertical={false} />
                <XAxis dataKey="date" tick={{ fill: "#737373", fontSize: 11 }} />
                <YAxis tick={{ fill: "#737373", fontSize: 11 }} width={34} />
                <Tooltip {...TT} itemStyle={{ color: "#38bdf8" }} cursor={{ fill: "#ffffff10" }} />
                <Bar dataKey="steps" fill="#38bdf8" radius={[4, 4, 0, 0]} />
              </BarChart>
            </Chart>
          </Card>

          <Card title="Stress">
            <Chart has={stress.length > 0} empty="no stress samples yet">
              <AreaChart data={stress} margin={{ top: 6, right: 10, bottom: 0, left: -14 }}>
                <CartesianGrid stroke="#262626" vertical={false} />
                <XAxis dataKey="time" tick={{ fill: "#737373", fontSize: 11 }} minTickGap={40} />
                <YAxis domain={[0, 100]} tick={{ fill: "#737373", fontSize: 11 }} width={34} />
                <Tooltip {...TT} itemStyle={{ color: "#fbbf24" }} />
                <Area type="monotone" dataKey="stress" stroke="#fbbf24" fill="#fbbf2433" strokeWidth={2} isAnimationActive={false} />
              </AreaChart>
            </Chart>
          </Card>

          <Card title="Activity heart rate · recent">
            <Chart has={actHr.length > 1} empty="no recorded HR yet">
              <LineChart data={actHr} margin={{ top: 6, right: 10, bottom: 0, left: -14 }}>
                <CartesianGrid stroke="#262626" vertical={false} />
                <XAxis dataKey="time" tick={{ fill: "#737373", fontSize: 11 }} minTickGap={48} />
                <YAxis domain={[(v: number) => Math.floor(v - 5), (v: number) => Math.ceil(v + 5)]} tick={{ fill: "#737373", fontSize: 11 }} width={34} allowDecimals={false} />
                <Tooltip {...TT} itemStyle={{ color: "#f472b6" }} />
                <Line type="monotone" dataKey="hr" stroke="#f472b6" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </Chart>
          </Card>

          <Card title="Resting HR / SpO₂">
            <Chart has={rhr.length > 0 || spo2.length > 0} empty="builds up as you wear it (sleep + rest)">
              <LineChart margin={{ top: 6, right: 10, bottom: 0, left: -14 }}>
                <CartesianGrid stroke="#262626" vertical={false} />
                <XAxis dataKey="time" type="category" allowDuplicatedCategory={false} tick={{ fill: "#737373", fontSize: 11 }} minTickGap={40} />
                <YAxis tick={{ fill: "#737373", fontSize: 11 }} width={34} />
                <Tooltip {...TT} />
                <Line data={rhr} dataKey="hr" name="resting HR" stroke="#a78bfa" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line data={spo2} dataKey="spo2" name="SpO₂" stroke="#22d3ee" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </Chart>
          </Card>
        </div>

        {/* Oura ring */}
        <section className="mt-8">
          <div className="mb-3 flex items-center gap-2">
            <h2 className="text-lg font-semibold tracking-tight">Oura Ring</h2>
            <span className="text-xs text-neutral-500">
              {oura?.updated ? "recovery & sleep" : "add token to enable"}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Readiness" value={readiness.length ? readiness[readiness.length - 1].score ?? "—" : "—"} unit="" color="text-emerald-400" big />
            <Stat label="Sleep last night" value={lastNight ? lastNight.total_h : "—"} unit="h" color="text-indigo-400" big />
            <Stat label="HRV" value={lastNight?.hrv ?? "—"} unit="ms" color="text-teal-300" big />
            <Stat label="Resting HR" value={lastNight?.resting_hr ?? "—"} unit="bpm" color="text-violet-300" big />
          </div>
          <div className="mt-4">
            <Card title="Oura HR · intraday (cloud — fills in when the ring syncs / on a Live HR reading)">
              <Chart has={ouraHr.length > 1} empty="no synced HR yet — turn iPhone BT on, open Oura, try Live Heart Rate">
                <LineChart data={ouraHr} margin={{ top: 6, right: 10, bottom: 0, left: -14 }}>
                  <CartesianGrid stroke="#262626" vertical={false} />
                  <XAxis dataKey="time" tick={{ fill: "#737373", fontSize: 11 }} minTickGap={48} />
                  <YAxis domain={[(v: number) => Math.floor(v - 5), (v: number) => Math.ceil(v + 5)]} tick={{ fill: "#737373", fontSize: 11 }} width={34} allowDecimals={false} />
                  <Tooltip {...TT} itemStyle={{ color: "#22d3ee" }} />
                  <Line type="monotone" dataKey="bpm" stroke="#22d3ee" strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </Chart>
            </Card>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card title="HRV · nightly (Oura)">
              <Chart has={hrvSeries.length > 0} empty="add your Oura token to see HRV">
                <LineChart data={hrvSeries} margin={{ top: 6, right: 10, bottom: 0, left: -14 }}>
                  <CartesianGrid stroke="#262626" vertical={false} />
                  <XAxis dataKey="day" tick={{ fill: "#737373", fontSize: 11 }} minTickGap={24} />
                  <YAxis tick={{ fill: "#737373", fontSize: 11 }} width={34} />
                  <Tooltip {...TT} itemStyle={{ color: "#2dd4bf" }} />
                  <Line type="monotone" dataKey="hrv" stroke="#2dd4bf" strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </Chart>
            </Card>
            <Card title="Sleep stages · hours/night (Oura)">
              <Chart has={sleepStages.length > 0} empty="add your Oura token to see sleep">
                <BarChart data={sleepStages} margin={{ top: 6, right: 10, bottom: 0, left: -14 }}>
                  <CartesianGrid stroke="#262626" vertical={false} />
                  <XAxis dataKey="day" tick={{ fill: "#737373", fontSize: 11 }} minTickGap={24} />
                  <YAxis tick={{ fill: "#737373", fontSize: 11 }} width={34} />
                  <Tooltip {...TT} cursor={{ fill: "#ffffff10" }} />
                  <Bar dataKey="deep" stackId="s" fill="#6366f1" name="deep" />
                  <Bar dataKey="rem" stackId="s" fill="#a78bfa" name="rem" />
                  <Bar dataKey="light" stackId="s" fill="#c7d2fe" name="light" radius={[4, 4, 0, 0]} />
                </BarChart>
              </Chart>
            </Card>
          </div>
        </section>

        {/* Insights / Data Science */}
        <section className="mt-8">
          <div className="mb-3 flex items-center gap-2">
            <h2 className="text-lg font-semibold tracking-tight">Insights · Data Science</h2>
            <span className="text-xs text-neutral-500">n=1 · {ins?.n_nights ?? 0} nights · associations, not proof</span>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Recovery Score" value={rec?.today ?? "—"} unit="/100" color={recColor} big />
            <Stat label="HRV vs baseline" value={hrvDev?.value_sd != null ? `${hrvDev.value_sd > 0 ? "+" : ""}${hrvDev.value_sd}` : "—"} unit={`SD · ${hrvDev?.label ?? ""}`} color="text-teal-300" />
            <Stat label="Resting HR trend" value={rhrTrend != null ? `${rhrTrend > 0 ? "+" : ""}${rhrTrend}` : "—"} unit="bpm/wk" color={rhrTrend != null && rhrTrend < 0 ? "text-emerald-400" : "text-violet-300"} />
            <Stat label="Recovery vs Oura" value={rec?.validation?.pearson_r != null ? `r=${rec.validation.pearson_r}` : "—"} unit={`n=${rec?.validation?.n ?? 0}`} color="text-emerald-300" />
          </div>

          <div className="mt-4">
            <Card title="Findings — ranked (green = strong, amber = moderate, grey = exploratory)">
              {(ins?.insights?.length ?? 0) === 0 ? (
                <div className="py-6 text-center text-sm text-neutral-600">computing… (needs a few nights of data)</div>
              ) : (
                <div className="space-y-2">
                  {(ins?.insights ?? []).map((it) => (
                    <div key={it.rank} className={`rounded-lg border-l-2 bg-neutral-900/40 px-3 py-2 ${it.strength === "strong" ? "border-emerald-400" : it.strength === "moderate" ? "border-amber-400" : "border-neutral-700"}`}>
                      <div className="text-sm text-neutral-200">{it.text}</div>
                      <div className="text-xs text-neutral-500">{it.strength}{it.evidence.p != null ? ` · p=${it.evidence.p}` : ""} · {it.hedge}</div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card title="Top cross-domain correlations (faded = not FDR-significant)">
              <Chart has={corrBars.length > 0} empty="needs more nights">
                <BarChart layout="vertical" data={corrBars} margin={{ top: 6, right: 16, bottom: 0, left: 8 }}>
                  <CartesianGrid stroke="#262626" horizontal={false} />
                  <XAxis type="number" domain={[-1, 1]} tick={{ fill: "#737373", fontSize: 11 }} />
                  <YAxis type="category" dataKey="name" width={120} tick={{ fill: "#a3a3a3", fontSize: 10 }} />
                  <Tooltip {...TT} />
                  <Bar dataKey="r">
                    {corrBars.map((b, i) => (<Cell key={i} fill={b.r >= 0 ? "#34d399" : "#fb7185"} fillOpacity={b.sig ? 1 : 0.4} />))}
                  </Bar>
                </BarChart>
              </Chart>
            </Card>

            <Card title={`HRV trend + 7-night baseline (${ins?.trends?.hrv?.direction ?? "—"})`}>
              <Chart has={hrvTrend.length > 1} empty="needs more nights">
                <LineChart data={hrvTrend} margin={{ top: 6, right: 10, bottom: 0, left: -14 }}>
                  <CartesianGrid stroke="#262626" vertical={false} />
                  <XAxis dataKey="day" tick={{ fill: "#737373", fontSize: 11 }} minTickGap={24} />
                  <YAxis tick={{ fill: "#737373", fontSize: 11 }} width={34} />
                  <Tooltip {...TT} />
                  <Line type="monotone" dataKey="value" name="HRV" stroke="#2dd4bf" strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="baseline" name="baseline" stroke="#737373" strokeWidth={1} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
                </LineChart>
              </Chart>
            </Card>

            <Card title="Circadian HR · strap, by hour">
              <Chart has={circadian.length > 2} empty="fills in as the strap logs more hours">
                <LineChart data={circadian} margin={{ top: 6, right: 10, bottom: 0, left: -14 }}>
                  <CartesianGrid stroke="#262626" vertical={false} />
                  <XAxis dataKey="hour" tick={{ fill: "#737373", fontSize: 11 }} />
                  <YAxis tick={{ fill: "#737373", fontSize: 11 }} width={34} />
                  <Tooltip {...TT} itemStyle={{ color: "#fb7185" }} />
                  <Line type="monotone" dataKey="hr" stroke="#fb7185" strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </Chart>
            </Card>

            <Card title={stressVsHr ? `Stress vs HR · r=${stressVsHr.pearson_r}, n=${stressVsHr.n}` : "Stress vs HR (strap)"}>
              <Chart has={stressScatter.length > 2} empty="needs overlapping stress + HR samples">
                <ScatterChart margin={{ top: 6, right: 10, bottom: 0, left: -14 }}>
                  <CartesianGrid stroke="#262626" />
                  <XAxis type="number" dataKey="stress" name="stress" domain={[0, 100]} tick={{ fill: "#737373", fontSize: 11 }} />
                  <YAxis type="number" dataKey="hr" name="hr" tick={{ fill: "#737373", fontSize: 11 }} width={34} />
                  <Tooltip {...TT} cursor={{ strokeDasharray: "3 3" }} />
                  <Scatter data={stressScatter} fill="#fbbf24" fillOpacity={0.5} />
                </ScatterChart>
              </Chart>
            </Card>
          </div>
        </section>

        <p className="mt-6 text-xs text-neutral-600">
          Live (HR, steps, battery) over the encrypted Huami-2021 channel; history (activity, stress,
          PAI, resting-HR, SpO₂) via the plaintext activity-fetch protocol. Stored in helio.db.
          {hist?.counts ? ` · rows: ${Object.entries(hist.counts).map(([k, v]) => `${k} ${v}`).join(", ")}` : ""}
        </p>
      </div>
    </main>
  );
}

function Stat({ label, value, unit, color, big }: {
  label: string; value: ReactNode; unit: string; color: string; big?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-neutral-800 bg-neutral-900/50 p-4">
      <div className="mb-1 text-xs text-neutral-400">{label}</div>
      <div className="flex items-baseline gap-1.5">
        <span className={`font-bold tabular-nums ${color} ${big ? "text-4xl" : "text-2xl"}`}>{value}</span>
        {unit && <span className="text-sm text-neutral-500">{unit}</span>}
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-neutral-800 bg-neutral-900/50 p-4 md:p-5">
      <h2 className="mb-3 text-sm text-neutral-400">{title}</h2>
      {children}
    </div>
  );
}

function Chart({ has, empty, children }: { has: boolean; empty: string; children: React.ReactElement }) {
  if (!has) {
    return <div className="flex h-48 items-center justify-center text-sm text-neutral-600">{empty}</div>;
  }
  return (
    <div className="h-48">
      <ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer>
    </div>
  );
}
