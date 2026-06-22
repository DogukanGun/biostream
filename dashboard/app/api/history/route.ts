import { readFile } from "node:fs/promises";
import path from "node:path";

// collector.py writes ../data/history.json (relative to the dashboard dir)
const HIST = path.join(process.cwd(), "..", "data", "history.json");

// async fs access -> request-time (Next 16 does not cache GET handlers by default)
export async function GET() {
  try {
    const raw = await readFile(HIST, "utf8");
    return Response.json(JSON.parse(raw));
  } catch {
    return Response.json({
      updated: null,
      activity_recent: [],
      steps_by_day: [],
      sleep_by_night: [],
      resting_hr: [],
      spo2: [],
      stress: [],
      pai: [],
      counts: {},
    });
  }
}
