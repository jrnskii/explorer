"use client"

import { useState } from "react"

import { CityPicker, type City } from "./city-picker"

const CITIES: City[] = [
  { id: "lon", name: "London", country: "United Kingdom", code: "LON", lat: 51.5074, lon: -0.1278 },
  { id: "par", name: "Paris", country: "France", code: "PAR" },
  { id: "ber", name: "Berlin", country: "Germany", code: "BER" },
  { id: "rom", name: "Rome", country: "Italy", code: "ROM" },
  { id: "mad", name: "Madrid", country: "Spain", code: "MAD" },
  { id: "bcn", name: "Barcelona", country: "Spain", code: "BCN", lat: 41.3874, lon: 2.1686 },
  { id: "ams", name: "Amsterdam", country: "Netherlands", code: "AMS" },
  { id: "vno", name: "Vilnius", country: "Lithuania", code: "VNO" },
  { id: "prg", name: "Prague", country: "Czechia", code: "PRG" },
  { id: "nyc", name: "New York", country: "United States", code: "NYC", lat: 40.7128, lon: -74.006 },
  { id: "tyo", name: "Tokyo", country: "Japan", code: "TYO", lat: 35.6762, lon: 139.6503 },
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
