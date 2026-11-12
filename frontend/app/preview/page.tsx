import { previews } from "./registry.generated"

export const metadata = { title: "Component preview" }

export default function PreviewPage() {
  return (
    <main className="mx-auto flex w-full max-w-4xl flex-col gap-8 p-8">
      <header>
        <h1 className="text-2xl font-semibold">Component preview</h1>
        <p className="text-sm text-muted-foreground">
          Add a <code>components/&lt;name&gt;.preview.tsx</code> file with a default export to
          show up here.
        </p>
      </header>
      {previews.length === 0 && (
        <p className="text-muted-foreground">No previews found.</p>
      )}
      {previews.map(({ name, Component }) => (
        <section key={name} id={name} className="rounded-xl border">
          <h2 className="border-b px-4 py-2 font-mono text-sm text-muted-foreground">
            {name}
          </h2>
          <div className="p-6">
            <Component />
          </div>
        </section>
      ))}
    </main>
  )
}
