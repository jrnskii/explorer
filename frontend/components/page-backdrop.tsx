"use client"

import { CloudOverlay } from "@/components/cloud-overlay"
import { EuropeLoader } from "@/components/europe-loader"

// Transparent in the middle, fully opaque at the viewport borders: the blur fades in toward the edges.
const EDGE_MASK =
  "radial-gradient(ellipse at center, transparent 55%, black 100%)"

// Fades the page background colour in from the viewport borders (white in the light theme).
const VIGNETTE =
  "radial-gradient(ellipse at center, transparent 50%, color-mix(in srgb, var(--vignette) 85%, transparent) 100%)"

/**
 * The still satellite map, clouds and edge vignette used behind the homepage,
 * for secondary pages that share its look. Decorative only.
 */
export function PageBackdrop() {
  return (
    <div aria-hidden data-testid="page-backdrop">
      <EuropeLoader
        className="fixed inset-0 z-0 h-screen min-h-0"
        label="Europe map"
        loading={false}
        satellite
      />
      <div
        className="pointer-events-none fixed inset-0 z-[1] backdrop-blur-md"
        style={{ maskImage: EDGE_MASK, WebkitMaskImage: EDGE_MASK }}
      />
      <CloudOverlay className="fixed inset-0 z-[1] h-screen" denseTop />
      <div
        className="pointer-events-none fixed inset-0 z-[1] [--vignette:white] dark:[--vignette:var(--background)]"
        style={{ background: VIGNETTE }}
      />
    </div>
  )
}
