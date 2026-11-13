export type Capital = {
  name: string
  country: string
  lat: number
  lon: number
}

// All 27 EU member-state capitals (WGS84 lat/lon).
export const EU_CAPITALS: readonly Capital[] = [
  { name: "Vienna", country: "Austria", lat: 48.2082, lon: 16.3738 },
  { name: "Brussels", country: "Belgium", lat: 50.8503, lon: 4.3517 },
  { name: "Sofia", country: "Bulgaria", lat: 42.6977, lon: 23.3219 },
  { name: "Zagreb", country: "Croatia", lat: 45.815, lon: 15.9819 },
  { name: "Nicosia", country: "Cyprus", lat: 35.1856, lon: 33.3823 },
  { name: "Prague", country: "Czechia", lat: 50.0755, lon: 14.4378 },
  { name: "Copenhagen", country: "Denmark", lat: 55.6761, lon: 12.5683 },
  { name: "Tallinn", country: "Estonia", lat: 59.437, lon: 24.7536 },
  { name: "Helsinki", country: "Finland", lat: 60.1699, lon: 24.9384 },
  { name: "Paris", country: "France", lat: 48.8566, lon: 2.3522 },
  { name: "Berlin", country: "Germany", lat: 52.52, lon: 13.405 },
  { name: "Athens", country: "Greece", lat: 37.9838, lon: 23.7275 },
  { name: "Budapest", country: "Hungary", lat: 47.4979, lon: 19.0402 },
  { name: "Dublin", country: "Ireland", lat: 53.3498, lon: -6.2603 },
  { name: "Rome", country: "Italy", lat: 41.9028, lon: 12.4964 },
  { name: "Riga", country: "Latvia", lat: 56.9496, lon: 24.1052 },
  { name: "Vilnius", country: "Lithuania", lat: 54.6872, lon: 25.2797 },
  { name: "Luxembourg", country: "Luxembourg", lat: 49.6116, lon: 6.1319 },
  { name: "Valletta", country: "Malta", lat: 35.8989, lon: 14.5146 },
  { name: "Amsterdam", country: "Netherlands", lat: 52.3676, lon: 4.9041 },
  { name: "Warsaw", country: "Poland", lat: 52.2297, lon: 21.0122 },
  { name: "Lisbon", country: "Portugal", lat: 38.7223, lon: -9.1393 },
  { name: "Bucharest", country: "Romania", lat: 44.4268, lon: 26.1025 },
  { name: "Bratislava", country: "Slovakia", lat: 48.1486, lon: 17.1077 },
  { name: "Ljubljana", country: "Slovenia", lat: 46.0569, lon: 14.5058 },
  { name: "Madrid", country: "Spain", lat: 40.4168, lon: -3.7038 },
  { name: "Stockholm", country: "Sweden", lat: 59.3293, lon: 18.0686 },
]
