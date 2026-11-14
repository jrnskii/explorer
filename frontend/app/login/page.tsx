import type { Metadata } from "next"

import { LoginForm } from "@/components/login-form"
import { PageBackdrop } from "@/components/page-backdrop"
import { SiteFooter } from "@/components/site-footer"
import { SiteHeader } from "@/components/site-header"

export const metadata: Metadata = {
  title: "Log in — Explorer",
  description: "Log in to your Explorer account.",
}

export default function LoginPage() {
  return (
    <>
      <PageBackdrop />
      <div className="relative z-10 mx-auto w-full max-w-5xl px-4 sm:px-6">
        <SiteHeader current="login" />
        <main className="py-6">
          <LoginForm />
        </main>
      </div>
      <SiteFooter className="relative z-10" />
    </>
  )
}
