"use client"

import "leaflet/dist/leaflet.css"

import { geoBounds } from "d3-geo"
import type { Feature, FeatureCollection } from "geojson"
import { latLngBounds } from "leaflet"
import { useCallback, useEffect, useState, type ReactNode } from "react"
import { GeoJSON, MapContainer, useMap, useMapEvents } from "react-leaflet"
import { feature } from "topojson-client"
import type { GeometryCollection, Topology } from "topojson-specification"
import countries50m from "world-atlas/countries-50m.json"

export type LonLat = readonly [number, number]
export type Projector = (lonLat: LonLat) => [number, number]

export type OverlayApi = {
  /** Projects [lon, lat] to pixel coordinates inside the map container. */
  project: Projector
  width: number
  height: number
}

const PADDING = 48

// Country outlines (Natural Earth via world-atlas), trimmed to Europe's surroundings.
const atlas = countries50m as unknown as Topology<{ countries: GeometryCollection }>
const REGION = { west: -35, south: 25, east: 50, north: 75 }
const COUNTRIES: FeatureCollection = (() => {
  const all = feature(atlas, atlas.objects.countries) as FeatureCollection
  const features = all.features.filter((f: Feature) => {
    const [[w, s], [e, n]] = geoBounds(f)
    // w > e means the feature crosses the antimeridian (e.g. Russia).
    const overlapsLon =
      w <= e ? e >= REGION.west && w <= REGION.east : e >= REGION.west || w <= REGION.east
    return overlapsLon && n >= REGION.south && s <= REGION.north
  })
  return { type: "FeatureCollection", features }
})()

// Non-interactive: the map is a backdrop for the loading animation.
const STATIC_MAP_OPTIONS = {
  zoomControl: false,
  dragging: false,
  scrollWheelZoom: false,
  doubleClickZoom: false,
  touchZoom: false,
  boxZoom: false,
  keyboard: false,
  zoomSnap: 0,
} as const

function Overlay({
  fit,
  children,
}: {
  fit: readonly LonLat[]
  children: (api: OverlayApi) => ReactNode
}) {
  const map = useMap()
  // Bumped whenever the map view changes so projected positions are recomputed.
  const [, setVersion] = useState(0)
  const bump = useCallback(() => setVersion((v) => v + 1), [])

  useMapEvents({ moveend: bump, zoomend: bump, resize: bump })

  // Keep every point in view as the container is resized.
  useEffect(() => {
    const bounds = latLngBounds(fit.map(([lon, lat]) => [lat, lon]))
    const refit = () => {
      map.invalidateSize({ animate: false })
      map.fitBounds(bounds, { padding: [PADDING, PADDING], animate: false })
      bump()
    }
    refit()
    const observer = new ResizeObserver(refit)
    observer.observe(map.getContainer())
    return () => observer.disconnect()
  }, [map, fit, bump])

  const size = map.getSize()
  const project: Projector = ([lon, lat]) => {
    const p = map.latLngToContainerPoint([lat, lon])
    return [p.x, p.y]
  }

  // Until the container has a size and the view is fitted, projection yields NaN.
  const [probeX, probeY] = project(fit[0] ?? [0, 0])
  if (size.x === 0 || size.y === 0 || !Number.isFinite(probeX + probeY)) {
    return null
  }

  return (
    <div className="pointer-events-none absolute inset-0 z-[500]">
      {children({ project, width: size.x, height: size.y })}
    </div>
  )
}

/**
 * Country-outline map (Leaflet + GeoJSON, no tiles) fitted to `fit`, with a
 * pixel-space overlay for custom drawing. Client-only: Leaflet needs `window`.
 */
export default function EuropeOsmMap(props: MapProps) {
  // Cache Components keeps a route's React state alive while hiding it on
  // client-side navigation, but runs effect cleanups, which destroy the
  // Leaflet map. Re-rendering the overlay against the destroyed map throws
  // (`el._leaflet_pos`), so the map is only mounted while effects are active
  // and is rebuilt from scratch when the route is shown again.
  const [active, setActive] = useState(false)
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setActive(true)
    return () => setActive(false)
  }, [])
  if (!active) return <div className={props.className} />
  return <LeafletMap {...props} />
}

type MapProps = {
  fit: readonly LonLat[]
  className?: string
  children: (api: OverlayApi) => ReactNode
}

function LeafletMap({ fit, className, children }: MapProps) {
  return (
    <MapContainer
      {...STATIC_MAP_OPTIONS}
      bounds={fit.map(([lon, lat]) => [lat, lon])}
      boundsOptions={{ padding: [PADDING, PADDING] }}
      className={className}
      attributionControl={false}
    >
      <GeoJSON
        data={COUNTRIES}
        interactive={false}
        style={{
          weight: 1,
          className: "fill-foreground/5 stroke-foreground/40",
        }}
      />
      <Overlay fit={fit}>{children}</Overlay>
    </MapContainer>
  )
}
