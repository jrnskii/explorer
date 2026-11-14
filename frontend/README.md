This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

Install dependencies with `bun install --frozen-lockfile`, then run the development server:

```bash
bun run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.

## Staging search

The home page sends the shared `RoundTripSearchInput` to `/api/round-trip`.
The server route authenticates to `BACKEND_GRAPHQL_URL` with the server-only
`APP_ACCESS_TOKEN`; credentials never enter the browser. The API executes the
shared SDL directly. City identifiers are the autocomplete catalog's GeoNames
IDs (`gn-…`), with no hardcoded city allowlist.

The backend ranks dated services from the prepared GTFS/forecast snapshot and
sends **only the single best opportunity** to Scrappa/Omio. It never sends all
candidates, retries a paid request automatically, or tries another route after
verification fails. The checked result uses provider-advertised fares and actual
provider timings, revalidated against the original constraints. Other results
remain labelled estimates (including any ranking calibration). If verification
fails, the page says so and labels all prices as estimates. Scrappa does not
promise final checkout fees; these require provider confirmation.

See [`docs/staging.md`](../docs/staging.md) for snapshot preparation, environment
configuration, container startup, readiness and refresh procedures. Run `just
staging` with `.env.staging` configured. Containers use production Next.js and
Uvicorn servers; the backend is accessible only on the Compose network.

For local processes, run `just api` with root `.env` containing `APP_ACCESS_TOKEN`,
`SCHEDULE_SNAPSHOT_PATH`, and `SCRAPPA_API_KEY`. In another terminal run
`bun run --cwd frontend dev`. Development startup reads `APP_ACCESS_TOKEN` and
`BACKEND_GRAPHQL_URL` from the root `.env` when they are not already set, and defaults
the backend URL to `http://127.0.0.1:8000/graphql`. Existing process settings and
`frontend/.env*` settings take precedence. If you use `just api 9000`, set
`BACKEND_GRAPHQL_URL=http://127.0.0.1:9000/graphql`. Restart the development server
after changing root `.env` settings.

The root fallback applies only to the development server. Production builds and
servers require explicit runtime configuration, as provided by Compose. Never
prefix credentials with `NEXT_PUBLIC_` or add them to `next.config`'s `env` option.

The v1 API prices one adult. Departure is a local calendar day converted to an
explicit-offset instant. A single duration is a maximum elapsed trip length;
ranges constrain the earliest and latest return. Unsupported form constraints
are reported rather than ignored. Date coverage and transport availability come
from the loaded data, not fabricated departures or fares. The page reports search
bounds and missing flight schedule coverage. The current GTFS compiler supplies
rail, bus and ferry schedules, not flights; static airline topology is never used
as a dated flight schedule.

Run `bun run --cwd frontend test`, `bun run --cwd frontend lint`,
`bun run --cwd frontend tsc --noEmit`, and `bun run --cwd frontend build`.

Search uses departure dates ±1 day and shows up to ten locally ranked routes.
Budget and minimum-city controls are removed. Routes cannot be simple A–B–A
returns or revisit intermediate cities. Only the best candidate (or runner-up
on failure) is provider-checked; other cards show date-only estimates without
booking actions. Missing provider quotes do not hide those estimates.
