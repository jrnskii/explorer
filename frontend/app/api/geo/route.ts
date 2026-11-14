import { currencyForCountry, parseCountryCode } from "@/lib/region"

const COUNTRY_HEADERS = [
  "x-vercel-ip-country",
  "cf-ipcountry",
  "cloudfront-viewer-country",
]

/**
 * Reports the caller's country (and its currency, when supported) from the
 * geo-IP header set by the hosting edge. No third-party lookup is made, so
 * values are `null` when running without such an edge (e.g. local dev).
 */
export function GET(request: Request) {
  let country: string | null = null
  for (const name of COUNTRY_HEADERS) {
    country = parseCountryCode(request.headers.get(name))
    if (country) break
  }
  return Response.json(
    { country, currency: country ? currencyForCountry(country) : null },
    { headers: { "Cache-Control": "private, no-store" } }
  )
}
