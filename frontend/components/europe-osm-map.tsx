"use client"

import "leaflet/dist/leaflet.css"

import type { Feature, FeatureCollection } from "geojson"
import {
  geoJSON,
  latLngBounds,
  map as createMap,
  tileLayer,
  type Map as LeafletMapInstance,
} from "leaflet"
import { useCallback, useEffect, useState, type ReactNode } from "react"
import { geoBounds } from "d3-geo"
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

// Esri World Imagery satellite tiles (no API key). The on-map attribution
// control is hidden by request; see `attributionControl` below.
const SATELLITE_TILES_URL =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
const SATELLITE_ATTRIBUTION =
  "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community"


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

const FADE = "opacity 700ms ease-in-out"

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
  map,
  fit,
  children,
}: {
  map: LeafletMapInstance
  fit: readonly LonLat[]
  children: (api: OverlayApi) => ReactNode
}) {
  // Bumped whenever the map view changes so projected positions are recomputed.
  const [, setVersion] = useState(0)
  const bump = useCallback(() => setVersion((v) => v + 1), [])

  useEffect(() => {
    map.on({ moveend: bump, zoomend: bump, resize: bump })
    return () => {
      map.off({ moveend: bump, zoomend: bump, resize: bump })
    }
  }, [map, bump])

  // Keep every point in view as the container is resized.
  useEffect(() => {
    const bounds = latLngBounds(fit.map(([lon, lat]) => [lat, lon]))
    const refit = () => {
      if (!map.getPane("mapPane")) return
      map.invalidateSize({ animate: false })
      map.fitBounds(bounds, { padding: [PADDING, PADDING], animate: false })
      bump()
    }
    refit()
    const observer = new ResizeObserver(refit)
    observer.observe(map.getContainer())
    return () => observer.disconnect()
  }, [map, fit, bump])

  // A removed map (effect cleanup, Fast Refresh) has no panes; projecting
  // against it throws `el._leaflet_pos`. Wait for the fresh instance instead.
  if (!map.getPane("mapPane")) return null

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
 * Satellite-imagery map (Leaflet + Esri tiles) fitted
 * to `fit`, with a pixel-space overlay for custom drawing. Client-only: Leaflet needs `window`.
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
  /** Show satellite imagery instead of plain country outlines. */
  satellite?: boolean
  fit: readonly LonLat[]
  className?: string
  children: (api: OverlayApi) => ReactNode
}

// The Leaflet map is created and removed in a single effect rather than via
// react-leaflet's `MapContainer`: under React Strict Mode its effect cleanup
// removes the map but never recreates it, so layers added afterwards throw
// (`this.getPane().appendChild`). Here every effect run owns a fresh map.
function LeafletMap({ fit, satellite = true, className, children }: MapProps) {
  const [node, setNode] = useState<HTMLDivElement | null>(null)
  const [map, setMap] = useState<LeafletMapInstance | null>(null)

  useEffect(() => {
    if (!node) return
    const instance = createMap(node, { ...STATIC_MAP_OPTIONS, attributionControl: false })
    instance.fitBounds(
      fit.map(([lon, lat]) => [lat, lon] as [number, number]),
      { padding: [PADDING, PADDING] }
    )
    // Country outlines are the resting state; the satellite tiles fade in over
    // them (see the `satellite` effect below).
    geoJSON(COUNTRIES, {
      interactive: false,
      style: {
        fill: false,
        weight: 1,
        className: "stroke-muted-foreground/40",
      },
    }).addTo(instance)
    tileLayer(SATELLITE_TILES_URL, {
      attribution: SATELLITE_ATTRIBUTION,
      maxZoom: 19,
    }).addTo(instance)
    const tilePane = instance.getPane("tilePane")
    if (tilePane) {
      tilePane.style.transition = FADE
      tilePane.style.opacity = "0"
    }

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMap(instance)
    return () => {
      instance.remove()
      setMap(null)
    }
    // `fit` is re-applied by <Overlay>; only (re)create the map with its node.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node])

  // Fade the imagery in and the outlines out together.
  useEffect(() => {
    if (!map) return
    const tilePane = map.getPane("tilePane")
    const overlayPane = map.getPane("overlayPane")
    if (tilePane) tilePane.style.opacity = satellite ? "1" : "0"
    if (overlayPane) {
      overlayPane.style.transition = FADE
      overlayPane.style.opacity = satellite ? "0" : "1"
    }
  }, [map, satellite])

  return (
    <div ref={setNode} className={className}>
      {map && (
        <Overlay map={map} fit={fit}>
          {children}
        </Overlay>
      )}
    </div>
  )
}
