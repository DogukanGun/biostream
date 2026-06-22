import { readFile } from "node:fs/promises";
import path from "node:path";

// analyze.py writes ../data/insights.json (relative to the dashboard dir)
const INSIGHTS = path.join(process.cwd(), "..", "data", "insights.json");

export async function GET() {
  try {
    const raw = await readFile(INSIGHTS, "utf8");
    return Response.json(JSON.parse(raw));
  } catch {
    return Response.json({
      updated: null,
      window_days: 30,
      n_nights: 0,
      caveats: { subject_n: 1, note: "" },
      recovery: { today: null, trend: [], validation: { pearson_r: null, n: 0, verdict: "" } },
      derived: {
        hrv_baseline_deviation: { value_sd: null, label: "n/a" },
        rhr_trend_bpm_per_week: null,
        sleep_consistency: {},
      },
      correlations: [],
      trends: {},
      intraday: { available: false, circadian: [], zones: [], stress_vs_hr: null },
      insights: [],
    });
  }
}
