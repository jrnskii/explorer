import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, test } from "vitest"

import { LoginForm, validateLogin } from "./login-form"
import { SiteHeader } from "./site-header"

test("Log in nav item links to /login in the same tab", () => {
  render(<SiteHeader current="login" />)
  const link = screen.getByRole("link", { name: "Log in" })
  expect(link).toHaveAttribute("href", "/login")
  expect(link).toHaveAttribute("aria-current", "page")
  expect(link).not.toHaveAttribute("target")
})

describe("validateLogin", () => {
  test("accepts a valid email and password", () => {
    expect(validateLogin("a@b.co", "secret")).toEqual({})
    expect(validateLogin("  a@b.co  ", "x")).toEqual({})
  })

  test.each(["", "   ", "nope", "a@b", "a b@c.de"])(
    "rejects invalid email %j",
    (email) => {
      expect(validateLogin(email, "secret").email).toBeDefined()
    }
  )

  test("rejects empty password", () => {
    expect(validateLogin("a@b.co", "").password).toBeDefined()
  })
})

describe("LoginForm", () => {
  test("renders labelled fields and heading", () => {
    render(<LoginForm />)
    expect(
      screen.getByRole("heading", { level: 1, name: "Welcome back." })
    ).toBeInTheDocument()
    expect(screen.getByLabelText("Email")).toHaveAttribute("type", "email")
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password")
    expect(screen.queryByRole("status")).not.toBeInTheDocument()
  })

  test("shows validation errors and no notice for empty submit", async () => {
    const user = userEvent.setup()
    render(<LoginForm />)
    await user.click(screen.getByRole("button", { name: "Log in" }))
    expect(screen.getByText("Enter your email address.")).toBeInTheDocument()
    expect(screen.getByText("Enter your password.")).toBeInTheDocument()
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true")
    expect(screen.queryByRole("status")).not.toBeInTheDocument()
  })

  test("flags a malformed email", async () => {
    const user = userEvent.setup()
    render(<LoginForm />)
    await user.type(screen.getByLabelText("Email"), "nope")
    await user.type(screen.getByLabelText("Password"), "secret")
    await user.click(screen.getByRole("button", { name: "Log in" }))
    expect(screen.getByText("Enter a valid email address.")).toBeInTheDocument()
    expect(screen.queryByText("Enter your password.")).not.toBeInTheDocument()
  })

  test("valid submit shows coming-soon notice without claiming login", async () => {
    const user = userEvent.setup()
    render(<LoginForm />)
    await user.type(screen.getByLabelText("Email"), "a@b.co")
    await user.type(screen.getByLabelText("Password"), "secret{Enter}")
    const notice = screen.getByRole("status")
    expect(notice).toHaveTextContent("Log in coming soon.")
    expect(notice).toHaveTextContent(/no login has taken place/)
    expect(screen.queryByText("Enter your email address.")).not.toBeInTheDocument()
  })
})
