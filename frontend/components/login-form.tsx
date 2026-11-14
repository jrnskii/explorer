"use client"

import { useState, type FormEvent } from "react"
import Link from "next/link"
import { Info } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"

type Errors = { email?: string; password?: string }

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function validateLogin(email: string, password: string): Errors {
  const errors: Errors = {}
  const trimmed = email.trim()
  if (!trimmed) errors.email = "Enter your email address."
  else if (!EMAIL_PATTERN.test(trimmed))
    errors.email = "Enter a valid email address."
  if (!password) errors.password = "Enter your password."
  return errors
}

export function LoginForm() {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [errors, setErrors] = useState<Errors>({})
  const [submitted, setSubmitted] = useState(false)

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const next = validateLogin(email, password)
    setErrors(next)
    setSubmitted(Object.keys(next).length === 0)
  }

  return (
    <section
      aria-labelledby="login-title"
      className="mx-auto flex w-full max-w-md flex-col gap-6 rounded-xl border border-sage bg-background/85 p-6 text-foreground backdrop-blur-md sm:p-8"
    >
      <div>
        <h1 id="login-title" className="text-3xl font-semibold">
          Welcome back.
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Log in to see your saved trips and credits.
        </p>
      </div>

      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-5">
        <FieldGroup>
          <Field data-invalid={errors.email ? true : undefined}>
            <FieldLabel htmlFor="login-email">Email</FieldLabel>
            <Input
              id="login-email"
              name="email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-invalid={errors.email ? true : undefined}
              aria-describedby={errors.email ? "login-email-error" : undefined}
              className="h-10"
            />
            {errors.email && (
              <FieldError id="login-email-error">{errors.email}</FieldError>
            )}
          </Field>
          <Field data-invalid={errors.password ? true : undefined}>
            <FieldLabel htmlFor="login-password">Password</FieldLabel>
            <Input
              id="login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={errors.password ? true : undefined}
              aria-describedby={
                errors.password ? "login-password-error" : undefined
              }
              className="h-10"
            />
            {errors.password && (
              <FieldError id="login-password-error">
                {errors.password}
              </FieldError>
            )}
          </Field>
        </FieldGroup>

        <Button
          type="submit"
          className="h-10 w-full rounded-full bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-deep"
        >
          Log in
        </Button>

        {submitted && (
          <p
            role="status"
            className="flex items-start gap-2 rounded-xl border border-sage bg-card p-3 text-sm"
          >
            <Info aria-hidden className="mt-0.5 size-4 shrink-0 text-forest" />
            <span>
              <span className="font-semibold">Log in coming soon.</span>{" "}
              <span className="text-muted-foreground">
                Accounts are not available yet, so no login has taken place.
              </span>
            </span>
          </p>
        )}
      </form>

      <FieldDescription className="text-center">
        New to Explorer?{" "}
        <Link
          href="/pricing"
          className="font-medium text-forest underline underline-offset-4"
        >
          See pricing
        </Link>
      </FieldDescription>
    </section>
  )
}
