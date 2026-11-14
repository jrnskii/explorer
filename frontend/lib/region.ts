/** Currencies by ISO 3166-1 alpha-2 country, for the countries we offer. */
const COUNTRY_CURRENCY: Record<string, string> = {
  GB: "GBP",
  IE: "EUR",
  FR: "EUR",
  DE: "EUR",
  ES: "EUR",
  IT: "EUR",
  NL: "EUR",
  LT: "EUR",
  CZ: "CZK",
  PL: "PLN",
  US: "USD",
}

/** Normalises a country header value; returns null for missing/unknown codes. */
export function parseCountryCode(raw: string | null | undefined): string | null {
  const code = raw?.trim().toUpperCase()
  if (!code || !/^[A-Z]{2}$/.test(code) || code === "XX" || code === "T1") return null
  return code
}

export function currencyForCountry(country: string): string | null {
  return COUNTRY_CURRENCY[country] ?? null
}
