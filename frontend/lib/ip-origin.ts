import type { City } from "@/components/city-picker"
import { findEuropeCity } from "@/lib/europe-cities"

// Public IP geolocation (HTTPS, CORS enabled). Called with no address, it
// locates the caller, so the visitor's IP is shared with this provider.
const IP_LOOKUP_URL = "https://ipwho.is/?fields=success,country_code,capital"

export type IpOrigin = { countryCode: string; capital: string }

/** Country and capital for the caller's IP address, or null when unavailable. */
export async function lookupIpOrigin(signal?: AbortSignal): Promise<IpOrigin | null> {
  try {
    const res = await fetch(IP_LOOKUP_URL, { signal })
    if (!res.ok) return null
    const body: unknown = await res.json()
    if (typeof body !== "object" || body === null) return null
    const { success, country_code, capital } = body as Record<string, unknown>
    if (success !== true) return null
    if (typeof country_code !== "string" || typeof capital !== "string") return null
    if (!country_code.trim() || !capital.trim()) return null
    return { countryCode: country_code.trim(), capital: capital.trim() }
  } catch {
    return null
  }
}

/**
 * The capital of the visitor's IP country as a departure city. Resolves to
 * null when the lookup fails or the capital is outside the supported dataset.
 */
export async function detectDepartureCity(signal?: AbortSignal): Promise<City | null> {
  const origin = await lookupIpOrigin(signal)
  if (!origin) return null
  return findEuropeCity(origin.capital, origin.countryCode)
}
