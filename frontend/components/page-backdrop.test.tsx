import { render, screen } from "@testing-library/react"
import { expect, test, vi } from "vitest"

import { PageBackdrop } from "./page-backdrop"

vi.mock("@/components/europe-loader", () => ({
  EuropeLoader: ({ loading, satellite }: { loading: boolean; satellite: boolean }) => (
    <div data-testid="loader" data-loading={loading} data-satellite={satellite} />
  ),
}))
vi.mock("@/components/cloud-overlay", () => ({
  CloudOverlay: () => <canvas data-testid="clouds" />,
}))

test("renders a still satellite map with clouds, hidden from assistive technology", () => {
  render(<PageBackdrop />)
  expect(screen.getByTestId("page-backdrop")).toHaveAttribute("aria-hidden", "true")
  const loader = screen.getByTestId("loader")
  expect(loader).toHaveAttribute("data-satellite", "true")
  expect(loader).toHaveAttribute("data-loading", "false")
  expect(screen.getByTestId("clouds")).toBeInTheDocument()
})
