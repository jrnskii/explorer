import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, test } from "vitest"

import { Faq } from "./faq"
import { FAQ_ITEMS, filterFaq } from "@/lib/faq-data"

const trigger = (name: string | RegExp) =>
  screen.getByRole("button", { name })

test("contains all 18 questions, all collapsed by default", () => {
  render(<Faq />)
  expect(FAQ_ITEMS).toHaveLength(18)
  expect(screen.getByText("18 questions")).toBeInTheDocument()
  for (const item of FAQ_ITEMS) {
    expect(trigger(item.question)).toHaveAttribute("aria-expanded", "false")
  }
  expect(screen.queryByText(/Explorer helps students/)).not.toBeInTheDocument()
})

test("expands, collapses, and only one answer is open at a time (across categories)", async () => {
  const user = userEvent.setup()
  render(<Faq />)
  await user.click(trigger("What is Explorer?"))
  expect(trigger("What is Explorer?")).toHaveAttribute("aria-expanded", "true")
  expect(await screen.findByText(/Explorer helps students/)).toBeVisible()

  await user.click(trigger("Is Explorer free to use?"))
  expect(trigger("What is Explorer?")).toHaveAttribute("aria-expanded", "false")
  expect(trigger("Is Explorer free to use?")).toHaveAttribute("aria-expanded", "true")

  await user.click(trigger("Is Explorer free to use?"))
  expect(trigger("Is Explorer free to use?")).toHaveAttribute("aria-expanded", "false")
})

test("search filters by question and answer text and updates the count", async () => {
  const user = userEvent.setup()
  render(<Faq />)
  await user.type(screen.getByRole("searchbox", { name: "Search questions" }), "refund")
  expect(screen.getByText("1 question")).toBeInTheDocument()
  expect(trigger("What if I need to change or cancel a booking?")).toBeInTheDocument()
})

test("shows empty state with mailto link when nothing matches", async () => {
  const user = userEvent.setup()
  render(<Faq />)
  await user.type(screen.getByRole("searchbox"), "zzzzqq")
  expect(screen.getByText("0 questions")).toBeInTheDocument()
  const status = screen.getByText(/No matching questions found/)
  expect(within(status).getByRole("link", { name: "explorer@hack.com" })).toHaveAttribute(
    "href",
    "mailto:explorer@hack.com"
  )
})

test("category filters show only their questions and count", async () => {
  const user = userEvent.setup()
  render(<Faq />)
  await user.click(screen.getByRole("button", { name: "Booking & payments" }))
  expect(screen.getByText("3 questions")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "What is Explorer?" })).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Booking & payments" })).toHaveAttribute("aria-pressed", "true")
  await user.click(screen.getByRole("button", { name: "All questions" }))
  expect(screen.getByText("18 questions")).toBeInTheDocument()
})

test("category and search combine", () => {
  expect(filterFaq(FAQ_ITEMS, "membership", "credits")).toHaveLength(4)
  expect(filterFaq(FAQ_ITEMS, "booking", "credits")).toHaveLength(0)
})

test("credit pricing list and contact email link render when expanded", async () => {
  const user = userEvent.setup()
  render(<Faq />)
  await user.click(trigger("How much do Explorer credits cost?"))
  expect(await screen.findByText("5 credits — €2.99")).toBeInTheDocument()
  await user.click(trigger("How can I contact Explorer?"))
  const links = await screen.findAllByRole("link", { name: "explorer@hack.com" })
  for (const l of links) expect(l).toHaveAttribute("href", "mailto:explorer@hack.com")
})

test("Email Explorer button is a mailto link", () => {
  render(<Faq />)
  expect(screen.getByRole("link", { name: "Email Explorer" })).toHaveAttribute(
    "href",
    "mailto:explorer@hack.com"
  )
})
