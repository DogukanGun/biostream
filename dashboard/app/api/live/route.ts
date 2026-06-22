import { readFile } from "node:fs/promises";
import path from "node:path";

// collector.py writes ../data/live.json (relative to the dashboard dir)
const LIVE = path.join(process.cwd(), "..", "data", "live.json");

// Async fs access -> this handler runs at request time (not cached). Next 16
// does not cache GET route handlers by default, so each poll gets fresh data.
export async function GET() {
  try {
    const raw = await readFile(LIVE, "utf8");
    return Response.json(JSON.parse(raw));
  } catch {
    return Response.json({
      updated: null,
      connected: false,
      battery: null,
      hr: null,
      history: [],
    });
  }
}
