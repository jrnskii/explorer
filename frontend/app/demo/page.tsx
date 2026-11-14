import type { Metadata } from "next"

import { DemoHome } from "@/components/demo-home"

// Hidden demo route: not linked anywhere and kept out of search indexes.
export const metadata: Metadata = {
  title: "Demo",
  robots: { index: false, follow: false },
}

export default function DemoPage() {
  return <DemoHome />
}
