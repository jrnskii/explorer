// Generator for lib/data/europe-cities.json.
// Usage:
//   curl -LO https://download.geonames.org/export/dump/cities15000.zip && unzip cities15000.zip
//   bun scripts/gen-europe-cities.mjs /path/to/cities15000.txt
// Source data: GeoNames (https://www.geonames.org), CC BY 4.0 — cities with population >= 15000.
// Output rows: [geonameId, name, ISO country code, lat, lon], most populous first.
import { readFileSync, writeFileSync } from "node:fs"

const EUROPE = new Set(
  "AD AL AT AX BA BE BG BY CH CY CZ DE DK EE ES FI FO FR GB GG GI GR HR HU IE IM IS IT JE LI LT LU LV MC MD ME MK MT NL NO PL PT RO RS SE SI SK SM UA VA XK".split(" ")
)
// Countries that straddle the continental border: keep the European side only.
const WEST_OF = { RU: 45, TR: 30 }

const rows = []
for (const line of readFileSync(process.argv[2], "utf8").split("\n")) {
  if (!line) continue
  const f = line.split("\t")
  const [id, name, , , lat, lon, , , cc] = f
  const pop = Number(f[14])
  const limit = WEST_OF[cc]
  if (!EUROPE.has(cc) && limit === undefined) continue
  if (limit !== undefined && Number(lon) > limit) continue
  rows.push({ pop, row: [Number(id), name, cc, Number(Number(lat).toFixed(3)), Number(Number(lon).toFixed(3))] })
}
rows.sort((a, b) => b.pop - a.pop || a.row[1].localeCompare(b.row[1]))
writeFileSync(
  new URL("../lib/data/europe-cities.json", import.meta.url),
  JSON.stringify(rows.map((r) => r.row))
)
console.log(`wrote ${rows.length} cities`)
