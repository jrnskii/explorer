import { expect, test } from "vitest"

import { currencyForCountry, parseCountryCode } from "./region"

test("parseCountryCode normalises valid codes and rejects unknown ones", () => {
  expect(parseCountryCode(" lt ")).toBe("LT")
  for (const bad of [null, undefined, "", "XX", "T1", "USA", "1A"]) {
    expect(parseCountryCode(bad)).toBeNull()
  }
})

test("currencyForCountry maps supported countries only", () => {
  expect(currencyForCountry("DE")).toBe("EUR")
  expect(currencyForCountry("CZ")).toBe("CZK")
  expect(currencyForCountry("JP")).toBeNull()
})
