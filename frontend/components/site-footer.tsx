import { cn } from "@/lib/utils"
import { SUPPORT_EMAIL } from "@/lib/faq-data"

export function SiteFooter({ className }: { className?: string }) {
  return (
    <footer className={cn("mt-auto bg-deep text-footer-secondary", className)}>
      <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-2 border-footer-divider px-4 py-6 text-sm sm:px-6">
        <p>© Explorer. Plan affordable multi-city round trips.</p>
        <a
          href={`mailto:${SUPPORT_EMAIL}`}
          className="underline underline-offset-2 hover:text-white"
        >
          {SUPPORT_EMAIL}
        </a>
      </div>
    </footer>
  )
}
