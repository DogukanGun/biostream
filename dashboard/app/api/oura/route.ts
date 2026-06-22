import { readFile } from "node:fs/promises";
import path from "node:path";

// oura.py writes ../data/oura.json (relative to the dashboard dir)
const OURA = path.join(process.cwd(), "..", "data", "oura.json");

export async function GET() {
  try {
    const raw = await readFile(OURA, "utf8");
    return Response.json(JSON.parse(raw));
  } catch {
    return Response.json({
      updated: null,
      nights: [],
      readiness: [],
      sleep_score: [],
      spo2: [],
      activity: [],
    });
  }
}
