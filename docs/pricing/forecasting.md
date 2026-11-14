# Price forecasting implementation

## Objective and serving contract

Replace default random/constant demo prices with independently fitted models for
PLANES, TRAINS, BUSSES and FERRIES. Forecasts are EUR estimates for one adult,
one way, economy/second class where identifiable. They are never live quotes.
Unsupported routes return no forecast; missing model artifacts raise an actionable
error. Existing explicitly named mock fixtures remain available for offline tests.
Synthetic timetables remain synthetic and are labelled separately from prices.

## Model plan

1. Build an immutable, versioned JSON artifact from the extracted pricing DuckDB.
   Include input fingerprints, information date, coverage, model-specific evidence
   dates, fit policies and validation results. Do not load pickle models or train
   during a search. Use existing dependencies only.
2. Flights: fit a directional route/month median model using route/month aggregates
   only. Do not double count the overlapping whole-route aggregates or country
   summaries. Match the requested year/month, then the route baseline; do not infer
   annual seasonality from six months of data. Ranges describe variation of observed
   route/month medians, not calibrated intervals of individual ticket prices.
3. Buses: fit directional route/lead-time bucket medians from first-seat observations
   only. Group repeated query/service observations before fitting; never sum
   `totalfare`, use regression-transformed `fare1`, or count seat ladders as
   independent quotes. Route/lead evidence remains preferred; a screened distance
   regression can estimate unseen routes within a fitted geographic scope. Evidence is from 2017;
   explicitly disclose its age, and do not invent an inflation adjustment.
4. Rail: fit a route tariff-bound estimator from normal second-class SNCF tariffs,
   retaining operator/service differences in source evidence. The midpoint is an
   explicit tariff-based planning estimate, not an observed ticket-price label.
   Resolve UIC stations to nearby reference cities using the existing country-aware
   spatial index, retaining station names when no unique nearby city exists.
   Do not fabricate lead-time/seasonality effects from static tariff bounds.
5. Ferries: independent route-product model from EUR GTFS V1 products matched by
   feed and route. Accept only explicit route rules without zone constraints and
   reject fare products having any constrained rule; keep feed/route identity.
   Require a uniquely classified ferry route. Other currencies, zone/time/rider/media
   rules remain unsupported, rather than guessed or converted. The distance revision
   below can estimate an unmapped route within an already supported ferry feed.
6. Validate flights by holding out each route's last departure month (a cross-month
   diagnostic, not a historical booking-time backtest). Validate buses by holding
   out the latest query dates, keeping query/service groups together. Report sample
   counts, coverage and MAE on supported held-out units. Rail/ferry observed-fare
   validation is unavailable and must say so. Refit on eligible data after reporting
   held-out metrics. All training runs use explicit information dates; refuse a
   snapshot whose information is newer than that date.
7. Integrate a shared pricing boundary in the round-trip CLI and reactive notebooks.
   Keep the route solver price-source-independent. Reprice each purchase unit once;
   preserve parallel connections, operators, dates and synthetic-timetable labels.
   Never sum estimates across the segments of a bundled ticket. Reject unsupported
   mixed-mode bundles. Expose skipped coverage and model provenance outside the
   unchanged generated GraphQL schema. Forecast mode uses EUR budgets; mock mode
   remains explicit and uses USD. Missing models never trigger a mock fallback.
8. Add deterministic offline model, artifact, coverage, leakage, rounding, traveler,
   integration and CLI tests; train against local data and exercise actual forecasts.

## Scope and next iteration

This release is an empirical forecasting baseline, not a claim of current accuracy
across Schengen. There is no trustworthy all-Europe train/bus price history in the
current data. Distance estimates use fitted evidence within supported scopes and
distance ranges; extrapolation and unmatched scopes remain unsupported. GTFS
products are not automatically standalone itinerary fares. Current source licenses,
including the flight source's inconsistent license declarations, remain in the
artifact provenance; training locally does not resolve redistribution rights.

A later learned regression/quantile model needs newer observed rail/bus/ferry quotes,
collection timestamps, travel dates, class/passenger/baggage attributes, stable
route identities and geographically representative coverage. Evaluate against
route-median and lead-bucket baselines with chronological, service-grouped splits;
calibrate intervals on separate data and monitor drift before replacing these
baselines. Do not fit a model against synthetic prices or tariff midpoints and call
its fit observed-price accuracy.

## Integrated web preview

The web page consumes the same models through a bounded Node route handler and
the backend JSON batch CLI. Templates remain explicit sample itineraries; only
constraint-matching samples with every independent ticket priced are shown. Party
prices use exact decimal/integer-cent arithmetic and never fall back to preview
constants. This does not add live schedule search. Loading, errors, cancellation
and empty coverage are handled; the price integration has frontend tests. The local
Node host requires the adjacent backend environment and model artifact.


## Distance-aware revision (artifact version 2)

`just train-pricing --graph <base_graph.pickle>` now fits a separate nonnegative
log-distance regression for each mode. The default graph is
`fixtures/data/base_graph.pickle`; missing graph inputs fail clearly. The Python
training API accepts `graph_path=None` only for deliberately distance-free baseline
fixtures. Existing version-1 artifacts remain readable; retrain to enable distance.

The graph supplies `distance_km` with basis `city_centres_great_circle`. Direct
mode-specific edges are preferred. Fare routes often span intermediate graph
cities; for these, the same existing great-circle function derives the feature
from unique graph endpoint coordinates. This never establishes a timetable,
connection, reverse service or actual road/rail/water mileage. Forecast serving
uses a compact graph feature index in the artifact instead of loading the million-
edge graph on every request. The graph fingerprint and matching diagnostics are
stored with the fitted models.

Names/countries use the same canonical matching as price routes. Nearby city and
station aliases (e.g. Munich/München) prefer the single `Cities.csv` reference only
when every alias lies within the existing 10 km matching radius. Distant or
multiply sourced ambiguous city names stay unresolved. Parallel edges with
conflicting distances are excluded from the direct-distance index; source graph
nodes, edges, direction, operators and weights are never modified.

For each directional country pair (flights, buses and rail) or exact feed
(ferries), fit

```text
log(1 + unit_price) = intercept + slope * log(1 + distance_km)
slope >= 0
```

Each priced route contributes one median target, so months, seat ladders and
parallel edges cannot multiply its training weight. At least three independent
routes and varying distances are required to fit. Deterministic route-grouped
folds screen each regression against a scope-median baseline on the same held-out
routes. A fallback is enabled only when there is supported holdout evidence and
its MAE is no worse than the baseline. These folds are model-selection diagnostics,
not an independent final accuracy claim. Unsupported/sparse/losing regressions
remain recorded but disabled. Bus evidence covers only five routes and remains
historical; additional distance data alone does not solve that limitation.

Known excluded ferry routes (zone constraints, invalid/conflicting prices or
non-EUR definitions) are blocked from the distance fallback as well.

Known route/month, route/lead, rail tariff and ferry-product evidence stays
preferred. Distance is used for an unseen price route only when its country pair
or ferry feed has an enabled fit and the requested distance lies within its
training minimum/maximum. Exact flat ferry products are never increased just
because another segment is longer. Rail/ferry regression targets remain tariff
midpoints/published products; their error metrics do not measure real ticket-price
forecast accuracy. Ranges use fitted log residual extrema and remain descriptive,
not calibrated prediction intervals.

`ForecastQuery.distance_km` optionally accepts an already available graph feature;
the graph notebook passes its edge value directly. Other callers, including the
web batch boundary, infer it automatically from the fitted graph index. Forecast
responses include `distance_km` and `distance_source` (`request`, `base_graph_edge`,
or `base_graph_city_centres`). Explicit values must be finite and nonnegative.
Both the fitting and inference feature must use the graph's great-circle basis.
The batch CLI supports the same optional field. No generated GraphQL schema fields
are changed.

The flight temporal diagnostic now reports known-route baseline and additional
unseen-route distance coverage separately. Compare the distance fallback with its
scope median on the **same** added test units; overall MAE over expanded coverage
is not directly comparable with the old smaller-cohort MAE. Bus temporal splits
still group service/query observations and never train on held-out prices.


### Local validation snapshot (2026-11-14)

- Flight distances matched 11,135 priced routes. The last-month diagnostic retained
  9,403 route-baseline test units and added 1,278 distance-estimated units. On the
  added units only, MAE was EUR 70.63 versus EUR 71.41 for the matching scope median.
  Known-route baseline MAE stayed EUR 36.21; expanded-cohort overall MAE was EUR 40.33.
- All five bus routes matched graph geometry. The four-route German distance fit
  lost on its two supported held-out routes (EUR 2.97 vs EUR 2.00), so its fallback
  remains disabled. The existing route/lead temporal MAE stays EUR 2.79.
- Rail matched 3,289 tariff routes; the French fit's model-selection MAE against
  tariff midpoints was EUR 6.41 vs EUR 23.26 for its scope median. This is not an
  observed future-ticket-price validation.
- Ferry distances matched 12 product routes. One feed's five-route fit passed on
  three supported held-out product routes (EUR 0.24 vs EUR 0.87). Other feeds remain
  unsupported for distance inference.

These figures describe this local snapshot, not general European market accuracy.
Re-run training to regenerate model-specific diagnostics for updated inputs.

### One-route provider reconciliation

`find_round_trips(..., price_forecaster=estimator, exact_pricer=pricer)` now supports
staged pricing. `ForecastOfferEstimator` adapts the existing distance-aware,
mode-specific forecaster to whole scheduled purchases. Unsupported purchases are
reported in `result.pricing.unpriced_offer_ids` and excluded. Forecasting runs once
per eligible offer identity; no provider calls occur during traversal.

With an exact pricer, candidate retention and final selection use lowest estimated
price first, including in fuzzy searches. Only that one route is passed to
`quote`; failures never fall through to another route. Approximate budget pruning
is deferred until reconciliation so an overestimated route can still be checked.
Search-state/leg/result bounds still apply; this does not prove global optimality.

`ScrappaRoundTripPricer` supports direct one-way flights, trains and buses. It
requires reviewed application-city -> Omio position IDs; it does not guess IDs
from station names. Ferries and connection/bundled purchases fail preflight without
HTTP. Within the selected city/mode/date path, it chooses feasible actual services
and retrieves each chosen trip's details. One route check can therefore require
multiple API requests. Updated departure/arrival times must still satisfy the
search horizon, connections and return window. Available undiscounted one-way
fares are counted once per purchase; daily price floors are never accepted as fares.

Scrappa's [search](https://scrappa.co/docs/omio-api/omio_search) and
[trip](https://scrappa.co/docs/omio-api/omio_trip) endpoints expose provider-advertised
fares, not guaranteed final checkout fees. Checked results explicitly carry
`price_status=provider_advertised` and `fees_complete=false`.

If the checked total exceeds another candidate's estimate, add the observed
underestimation (`checked total - selected original estimate`) to every unchecked
candidate total. This common uplift preserves estimated gaps and makes the checked
route cheapest, with checked results winning ties. `approximate_price`,
`ranking_adjustment`, and `result.pricing.candidates` expose the original forecasts
and adjustments. These adjustments are planning policy, not observed fees or new
training labels. Budgets apply to returned totals; an over-budget checked route can
leave no results, with status `over_budget`. On provider failure, the status is
`unavailable` and affordable original estimates remain explicitly unverified.

The CLI runs forecast prices through this core integration. To enable Scrappa:

```sh
# places.json: a reviewed object mapping application city IDs to integer Omio IDs.
# Set SCRAPPA_API_KEY in your environment for uncached requests.
uv run --project backend --locked python -m backend.presentation.cli.round_trip \
  --request backend/examples/round_trip_forecast.json \
  --exact-best --scrappa-places /path/to/places.json \
  --scrappa-cache backend/data/scrappa.duckdb
```

Add `--cache-only` for offline verification. Forecast artifacts must already exist.
The CLI's timetable is still synthetic; only successfully checked fares/times are
provider supplied. CLI JSON includes `price_reconciliation` and aligned
`option_pricing` metadata in addition to the existing map contract. The frontend
price-preview endpoint remains an offline forecast endpoint.

Every Scrappa response, including upstream errors, is retained in the existing
append-only `responses` DuckDB table. Fresh responses are reused for up to one hour,
and failures are cached without automatic retries. Valid trip details additionally
populate `fare_observations` with price, currency, passenger cohort, route, actual
times, original observation time, and search/detail response IDs. Cache hits do not
duplicate observations or advance their observation time. All raw search results
remain available for future extraction; the structured table currently records the
selected services. These observations prepare future model updates; search does
not retrain models or automatically ingest this table into the current trainer.

The manual `just test-omio --date YYYY-MM-DD` probe writes to the same default
`responses` database. It requests all three modes sorted by departure; exact
verification requests a single mode sorted by price and then trip details. These
are different cache keys: a completed probe alone does not guarantee an offline
`--exact-best --cache-only` run. Both paths validate the returned route, date,
one-way scope, currency and passenger cohort before interpreting results. Invalid
cohorts remain archived as raw responses, without becoming fare observations.
The probe itself does not populate `fare_observations`, retrain models, or create
the reviewed application-city mapping required by `--scrappa-places`.
