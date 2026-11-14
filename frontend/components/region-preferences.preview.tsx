"use client"

import { useState } from "react"

import {
  DEFAULT_REGION_PREFERENCES,
  RegionPreferences,
  type RegionPreferencesValue,
} from "./region-preferences"

export default function RegionPreferencesPreview() {
  const [applied, setApplied] = useState<RegionPreferencesValue>(
    DEFAULT_REGION_PREFERENCES
  )

  return (
    <div className="flex flex-col items-start gap-4">
      <RegionPreferences onApply={setApplied} />
      <p className="text-sm text-muted-foreground">
        Applied: {applied.country} / {applied.currency}
      </p>
    </div>
  )
}
