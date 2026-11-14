This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
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

## Route search

The home page requests `/api/round-trip` with the selected city's GeoNames ID,
dates and transport modes. Configure `BACKEND_GRAPHQL_URL` and
`APP_ACCESS_TOKEN` on the frontend server and run the backend search service.
The service explores three nearby departure dates and ranks multi-city routes.
The page displays up to seven results, placing the provider-verified opportunity first and sorting the remaining estimates by price, including clearly labeled
route estimates when live fare verification is unavailable. Estimates have no
invented departure times or booking links. Prices are per adult; the current
search contract supports one adult. Genuine coverage gaps may return fewer
results, and service failures are displayed as errors.

## Local fare forecasts

The demo's `/api/pricing` endpoint prices sample itineraries. It is independent
of the home page's route search. Sample routes reject repeated cities and simple
out-and-back trips; fares use integer cents for arithmetic and ranking.

From the repository root run `just extract-pricing`, `just train-pricing`, and
`uv sync --project backend --locked` before starting the frontend. The Node server
requires the adjacent backend checkout, installed Python environment, `uv` on PATH,
and `fixtures/data/pricing/forecast_models.json`. Set `PRICING_UV_PATH` to the trusted
server executable's absolute path if necessary. Python and model data are provisioned
separately from the Next bundle; raw fixture datasets are not bundled. This local
integration requires a Node host with Python support, not Edge/static-only hosting.

The server invokes a fixed backend module with JSON stdin, never a user-provided
shell command. Limits are 64 queries/64 KiB, two active processes per server instance,
20 seconds and 1 MiB of output. Public errors do not expose backend paths or stderr.
No paid provider is called and there is no mock fallback. Browser aborts prevent
stale results; backend processes remain bounded by the server timeout.

Run `bun run --cwd frontend test` from the repository root. The minimal setup uses
Vitest, React Testing Library and jsdom. Tests cover loading, errors,
recovery, empty coverage, estimate validation, filtering, exact sums, party totals
and API input limits.

Cached Scrappa/Omio results use a four-second map showcase (zoom, route drawing,
and fade) before revealing results. The backend sets `provider_results_cached`
only when every search and trip-detail response for the verified option came
from cache; live or mixed responses keep the normal path-based duration.

Estimated routes retain one `transport_types` entry per leg, in city order.
The estimator filters to selected modes and uses each leg's mode-specific fare
forecast; cards show those planned modes without implying verified availability.

Older estimated-route responses without transport types remain displayable;
their leg details show “Transport unverified” until mode data is available.
