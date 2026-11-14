import { execFile } from "node:child_process"
import { resolve } from "node:path"

let active = 0

export async function POST(request: Request): Promise<Response> {
  const reader = request.body?.getReader()
  if (!reader) return Response.json({ error: "Invalid pricing request." }, { status: 400 })
  const chunks: Uint8Array[] = []
  let size = 0
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      size += value.byteLength
      if (size > 65536) {
        await reader.cancel()
        return Response.json({ error: "Pricing request is too large." }, { status: 413 })
      }
      chunks.push(value)
    }
  } catch { return Response.json({ error: "Invalid pricing request." }, { status: 400 }) }
  const raw = Buffer.concat(chunks).toString("utf8")
  let payload: unknown
  try { payload = JSON.parse(raw) } catch {
    return Response.json({ error: "Invalid pricing request." }, { status: 400 })
  }
  if (!payload || typeof payload !== "object" || !("queries" in payload) ||
      !Array.isArray(payload.queries) || payload.queries.length < 1 || payload.queries.length > 64) {
    return Response.json({ error: "Supply between 1 and 64 fare queries." }, { status: 400 })
  }
  const modes = new Set(["PLANES", "TRAINS", "BUSSES", "FERRIES"])
  if (!payload.queries.every((row: unknown) => {
    if (!row || typeof row !== "object" || !("mode" in row) || !modes.has(String(row.mode)) ||
        !("origin" in row) || typeof row.origin !== "string" || !row.origin.trim() || row.origin.length > 128 ||
        !("destination" in row) || typeof row.destination !== "string" || !row.destination.trim() || row.destination.length > 128 ||
        !("departure_date" in row) || typeof row.departure_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(row.departure_date)) return false
    const parsed = new Date(row.departure_date)
    if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== row.departure_date) return false
    return !("travelers" in row) || (typeof row.travelers === "number" && Number.isInteger(row.travelers) && row.travelers >= 1 && row.travelers <= 9)
  })) return Response.json({ error: "Invalid fare query." }, { status: 400 })
  if (active >= 2) return Response.json({ error: "Pricing is busy. Please try again." }, { status: 503 })
  active += 1
  try {
    const output = await new Promise<string>((accept, reject) => {
      // Fixed executable/arguments and JSON stdin; user input never enters a shell command.
      // Python and its model data are provisioned separately, outside the Next bundle.
      const child = execFile(/*turbopackIgnore: true*/ process.env.PRICING_UV_PATH || "uv", ["run", "--project",
        resolve(process.cwd(), "../backend"), "--locked", "--no-sync", "python", "-B", "-m",
        "backend.presentation.cli.forecast_prices"],
        { timeout: 20000, maxBuffer: 1024 * 1024 },
        (error, stdout) => error ? reject(error) : accept(stdout))
      child.stdin?.on("error", () => { /* Process exit is handled by the callback. */ })
      child.stdin?.end(raw)
    })
    return Response.json(JSON.parse(output))
  } catch {
    return Response.json({ error: "Price estimates are unavailable. Please try again later." }, { status: 503 })
  } finally { active -= 1 }
}
