import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, test, vi } from "vitest"

import { Button } from "./button"

test("calls onClick when activated with the mouse", async () => {
  const onClick = vi.fn()
  render(<Button onClick={onClick}>Search</Button>)

  await userEvent.click(screen.getByRole("button", { name: "Search" }))

  expect(onClick).toHaveBeenCalledTimes(1)
})

test("is keyboard accessible", async () => {
  const onClick = vi.fn()
  render(<Button onClick={onClick}>Search</Button>)

  await userEvent.tab()
  expect(screen.getByRole("button", { name: "Search" })).toHaveFocus()
  await userEvent.keyboard("{Enter}")

  expect(onClick).toHaveBeenCalledTimes(1)
})

test("does not fire onClick when disabled", async () => {
  const onClick = vi.fn()
  render(
    <Button disabled onClick={onClick}>
      Search
    </Button>,
  )

  await userEvent.click(screen.getByRole("button", { name: "Search" }))

  expect(onClick).not.toHaveBeenCalled()
})
