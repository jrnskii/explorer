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

## Local fare forecasts

The page requests `/api/pricing` to price its **sample itineraries**, replacing the
preview price constants. Dates shift to the selected calendar day; home, modes,
budget, stops and stay constraints filter the samples. Flexible-date exploration
is unsupported and returns a visible message. This remains a sample-itinerary
demonstration, not a full schedule search or booking service. An itinerary is
omitted if any independent one-way demo ticket lacks a forecast. Estimated totals
include travelers once. Backend arithmetic uses decimals; browser ticket sums and
budget comparisons use integer cents.

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
