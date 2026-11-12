"use client"

import { useState } from "react"

import { CityPicker, type City } from "./city-picker"

const CITIES: City[] = [
  { id: "lon", name: "London", country: "United Kingdom", code: "LON" },
  { id: "par", name: "Paris", country: "France", code: "PAR" },
  { id: "ber", name: "Berlin", country: "Germany", code: "BER" },
  { id: "rom", name: "Rome", country: "Italy", code: "ROM" },
  { id: "mad", name: "Madrid", country: "Spain", code: "MAD" },
  { id: "bcn", name: "Barcelona", country: "Spain", code: "BCN" },
  { id: "ams", name: "Amsterdam", country: "Netherlands", code: "AMS" },
  { id: "vno", name: "Vilnius", country: "Lithuania", code: "VNO" },
  { id: "prg", name: "Prague", country: "Czechia", code: "PRG" },
  { id: "nyc", name: "New York", country: "United States", code: "NYC" },
  { id: "tyo", name: "Tokyo", country: "Japan", code: "TYO" },
]

export default function CityPickerPreview() {
  const [from, setFrom] = useState<City | null>(null)
  const [to, setTo] = useState<City | null>(null)

  return (
    <div className="flex flex-col gap-4 sm:flex-row">
      <CityPicker label="From" value={from} onChange={setFrom} cities={CITIES} />
      <CityPicker label="To" value={to} onChange={setTo} cities={CITIES} />
    </div>
  )
}
