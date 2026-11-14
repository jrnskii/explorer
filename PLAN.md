# Round Trip application foundation

Status: proposed implementation plan, based on the repository inspected on 2026-11-13. This document changes no application behavior. Recommendations below are proposals; unresolved product choices are explicitly listed in section 15.

## 1. Product objective and boundaries

Help a traveler discover feasible round trips that start and finish in the same city, visit selected cities, and balance transport expense, travel time, and convenience. Represent cities as nodes in a directed multigraph, with plane, bus, train, and ferry travel opportunities connecting them. Preserve multiple services, departure dates, operators, and fares between the same cities.

The result must be an actionable itinerary, not merely a cheap path through a static graph. Every offered itinerary must obey schedules, transfer requirements, ticket conditions, allowed modes, city constraints, and the user's return window. Explain why it ranks well and distinguish confirmed provider facts from estimates and missing information.

Proposed first release:

- One adult, matching the existing shared contract; transport-only budget including mandatory transport fees. Accommodation, food, activities, visas, and travel insurance are outside that budget.
- A bounded launch geography and date horizon, chosen after measuring Ignav coverage. Existing European fixtures are test assets, not evidence of live coverage.
- Same-city return, unordered required cities, excluded cities, a budget ceiling, departure boundary, return target/window, and supported transport modes.
- Live flights through Ignav; other modes enabled only where a vetted source supplies sufficient data. Offline multimodal demonstrations remain explicitly synthetic.
- Compare several feasible alternatives and hand off to provider booking links where available. No payment processing, booking guarantee, or inventory reservation.

Later releases may add traveler parties, luggage preferences, ordered visits, accessibility needs, overnight-travel preferences, optional-city exploration, saved trips, alerts, and additional regions. Do not imply these are already supported by the v1 schema.

## 2. Existing foundation and concrete gaps

| Area | Current repository evidence | Planned treatment |
| --- | --- | --- |
| Backend layers | `backend/src/backend/domain/`, `application/`, `infrastructure/`, `presentation/`; architecture tests enforce boundaries | Extend these layers; keep provider and graph-library details out of domain logic |
| Travel graph | `infrastructure/graphs/weighted_graph.py` provides a directed multigraph with Decimal cost and duration in seconds | Retain as a static projection/test utility; it lacks schedules, currency identity per offer, terminals, transfers, and ticket constraints |
| Modes | Domain and shared schema contain `PLANES`, `TRAINS`, `BUSSES` | Add ferry support across contracts, adapters, fixtures, tests, and UI; preserve existing wire spelling unless deliberately migrated |
| Fare model | `domain/fares.py` preserves offers and ordered segment groups; price currently uses float | Introduce exact normalized money for planning without hand-editing generated provider models |
| Ignav mapping | `infrastructure/ignav/fare_search.py`, `graph.py`, and `application/fare_graph.py` validate/map supplied responses | Reuse mapping boundaries; add a live client and stricter planner eligibility validation |
| Fare projection | Airport nodes; segment occurrences retain bundled itinerary prices and index-based keys | Preserve diagnostic projection, but never solve purchasable itineraries by summing those edge prices |
| Fixtures | Seeded networks, fixed EU network, and mock Ignav responses | Reuse for deterministic tests; add schedule-feasible multimodal fixtures and explicit provenance |
| Static catalog/acquisition | Reference city/airline base graph; Mobility Database GTFS downloader and checkpointed archive combiner | Reuse tooling; add per-feed acceptance, canonical stop mappings, semantic GTFS import and schedule overlays; downloaded feeds are not automatically eligible |
| Shared API | `shared/graphql/schema_v1.graphql` defines round trips and constraints; generated Python/TS models exist | Implement application validation and an executable API; generated types alone are not a server or client |
| Frontend | `app/page.tsx` waits 800 ms and displays preview samples; city list is hardcoded | Replace demo orchestration with real search states and canonical city lookup |
| Search form | `trip-inputs.tsx` collects departure, EUR budget, calendar date, and duration | Reconcile with timestamp-based contract; add modes, required/excluded cities, return flexibility, and preferences |
| Results | `trip-opportunities.tsx` renders legs, UTC-based time strings, per-adult prices, and a rank-one “Cheapest” badge | Add local zones, transfer details, provenance, freshness, ranking explanations, and accurate badges |
| Tests/tooling | Backend unittest suite; frontend has no configured test script/runner | Preserve backend tests; establish minimal frontend behavior coverage when implementing UI changes |
| Persistence/runtime | Dependencies include FastAPI and DuckDB, but no live provider service, repository, or HTTP API is implemented | Select infrastructure from actual operational requirements, not merely installed packages |

City/airline reference snapshots are not current availability. Mobility Database archives can supply published GTFS schedules after semantic validation, but not live ticket inventory. Existing fixture coordinates may describe city centers rather than terminals. Do not promote reference or synthetic values into production facts.

## 3. Define constraints separately from preference weights

### Existing v1 semantics that must remain explicit

- `expenses_tolerance` is an absolute inclusive budget in a specified currency, not a percentage and not a ranking coefficient.
- `time_tolerance` is the maximum absolute deviation in minutes of final return arrival from `desired_arrival_date`. Zero means exact arrival time.
- Departure may never precede `departure_date`, regardless of tolerance.
- Every mandatory city must be visited; its list order is irrelevant.
- Excluded cities cannot appear as endpoints, including connections. Check internal segments of bundled offers as well as displayed city-to-city legs.
- Results currently sort by total price, then total travel time. Weighted preference ranking requires an explicit contract extension or version, not a silent behavioral change.

For target return instant R and tolerance Δ, the feasible return window is [R − Δ, R + Δ], inclusive. All actual travel must still occur after the permitted departure and in chronological order. Reject malformed or contradictory input rather than silently correcting it.

### Proposed preference model

Keep raw facts immutable: quoted money, departure/arrival instants, scheduled duration, and transfer requirements. Changing a slider changes selection or ranking, never a quoted fare or physical travel duration.

Expose two categories in the product:

1. **Limits/flexibility:** budget ceiling, return window, maximum transfers, maximum transport time, minimum visit duration, allowed modes. These determine eligibility.
2. **Preferences:** cheaper versus faster, fewer changes, less overnight travel, preferred modes. These rank eligible candidates.

A proposed itinerary score, lower being better:

`score = price_weight × price / price_scale + time_weight × transit_seconds / time_scale + change_weight × change_count / change_scale + discomfort_penalties`

Weights must be finite and nonnegative; reject an all-zero custom profile or use an explicitly documented default. Scales are positive, versioned, fixed for a search comparison, and independent of which candidates happen to be returned. Do not divide by a zero budget or zero tolerance. Keep penalties dimensionless and explainable. Store profile/version with results.

Transport time should include movement, required terminal processing, and transfer waiting; intentional city visits are separate. Show both transport burden and total elapsed trip duration. A longer holiday should not automatically look worse because sightseeing time was counted as transit.

Initially offer explicit “Cheapest” and “Least travel time” sorts; add a balanced profile after defining and validating its scales. Weighted sums can miss non-convex Pareto alternatives: preserve useful non-dominated candidates before final ranking. Never label the first balanced result “Cheapest” unless it actually has the lowest comparable total.

Example: given feasible trips at EUR 180/10 transit hours and EUR 230/6 transit hours, price preference can favor the former and time preference the latter. A EUR 200 ceiling excludes the latter regardless of preference weights. A return-window violation excludes either independently of score.

## 4. Domain model: cities, terminals, services, and offers

### Location identity

- `City`: stable internal ID, display names/aliases, country, geographic reference, and a documented timezone policy.
- `Terminal`: airport, railway station, bus station/stop, or ferry port; stable internal ID, canonical city membership, coordinates, IANA timezone, provider identifiers, and source/version.
- `ProviderLocationMapping`: provider namespace/code to terminal or city, mapping provenance, review status, and effective version.
- `TransferRule`: terminal pair, mode/context, minimum duration, available time window, cost status, source, and confidence.

City IDs must not be assumed to equal airport codes. A city can have multiple airports and stations; similarly named cities must remain distinct. Metropolitan grouping and nearby-airport inclusion require explicit policies. Unknown mappings are quarantined or reported as unavailable, not guessed into an itinerary.

### Scheduled movement and purchase identity

- `ServiceOccurrence`: mode, operator, origin/destination terminals, departure/arrival UTC instants, local timezones, service identifier, and source observation.
- `Journey`: ordered connected movements plus any required transfers.
- `FareOffer`: purchasable unit containing one or more journeys, original currency/amount, traveler basis, mandatory-fee completeness, booking reference, conditions, availability status, observation time, and expiry when supplied.
- `Visit`: city, arrival/departure bounds, intentional stay duration, and whether the stop satisfies a required visit.
- `Itinerary`: ordered movements, visits, selected purchase units, totals, normalized constraints, score breakdown, and freshness/coverage metadata.

Distinguish a physical service from its occurrence in several competing offers. Retain occurrence identity so duplicate/missing provider IDs cannot overwrite alternatives. Booking identity is not merely an edge key.

### Required invariants

- Every movement has positive elapsed duration and aware timestamps; use UTC for comparisons and local zones for display and calendar requests.
- Preserve parallel edges and directionality. Outbound availability does not imply an inbound service.
- Every transition accounts for disembarkation, terminal transfer, and required boarding/check-in time without double-counting overlapping buffers.
- Same city does not mean same terminal or a zero-minute connection. Unknown transfer feasibility must not be reported as confirmed.
- A visit is not automatically an airport connection. Proposed policy: required cities need an explicit visit event and minimum stay; settle the default before implementation.
- A valid round trip leaves home, visits at least one other city, and returns home within bounds. Proposed initial policy: the first return home completes the trip.
- Missing price is unknown, never zero. Schedule-only options must not appear as budget-verified purchasable trips.
- Unknown connection protection remains unknown; mixed carriers do not establish whether tickets are protected.

## 5. Graph representation and fare correctness

Maintain two related views:

1. **City connectivity graph:** cities as nodes, directed mode-specific routes as parallel edges. Useful for discovery, reachability, visualization, and safe lower bounds. Connectivity alone proves neither availability nor schedule feasibility.
2. **Scheduled planning state:** terminal-level events, journeys/offers, visit state, and time. This is the authority for constructing valid results; project it back into city-level itineraries for users.

Use on-demand outgoing-departure indexes over a bounded schedule horizon rather than constructing an unlimited global time-expanded graph. Keep graph storage behind application interfaces. Existing NetworkX adapters remain useful without forcing domain objects to inherit library classes.

### Bundled offers are indivisible purchase units

Ignav prices whole itineraries. A EUR 240 offer with two outbound segments and two inbound segments costs EUR 240 once, not EUR 960; none of its segments is automatically available for EUR 60 or for independent purchase.

Proposed progression:

- Support complete one-way journey offers as atomic search transitions, inspecting all internal segments for feasibility and exclusions.
- Support simple round trips by evaluating complete provider round-trip offers as whole candidates.
- Compose multi-city trips from separately purchasable one-way offers initially.
- Introduce coupled multi-journey offer selection only when search state tracks outstanding obligations and the offer is consumed in full, in order, under its terms. Until then, do not splice an outbound half from a round-trip fare into an unrelated circuit.

This makes early results correct but potentially more expensive than an advanced optimizer using bundled fares. State that limitation rather than claiming global price optimality. Fare allocation for display, if ever introduced, must be labeled accounting allocation and must not drive purchase feasibility.

## 6. Time-feasible round-trip search

### Request-to-result pipeline

1. Validate and normalize input, currency, city IDs, timestamp zones, supported modes, and search limits.
2. Resolve cities to supported terminals and determine coverage before making paid requests.
3. Build a bounded corridor/candidate set containing home, required cities, and optional discovery cities under a documented policy.
4. Retrieve cached eligible offers; request missing routes/dates under concurrency, time, and call budgets.
5. Normalize provider data; reject planner-ineligible schedules, missing money, inconsistent segments, or unknown identity mappings with diagnostics.
6. Index outgoing journeys by terminal and departure; compute only safe lower bounds.
7. Search feasible states, preserving purchase-unit integrity and visit constraints.
8. Independently validate every complete candidate, compute totals once per purchase unit, deduplicate, and rank.
9. Return results with search coverage, freshness, truncation, and warning metadata.
10. Revalidate selected offers before booking handoff where provider capabilities permit.

### Search state and pruning

A state needs current terminal/city, arrival time, required-city visit mask, accumulated money, transit burden, transfer count, route history as needed, and any coupled-offer obligations. Add visit completion only after stay requirements are met.

Start with bounded label-setting/label-correcting search over scheduled atomic journeys. Search all admissible required-city orders inside explicit limits rather than fixing the order greedily. Use departure indexes to skip missed services. Cap horizon, legs, city visits, labels, candidates, provider requests, and runtime; return the reason when a limit is reached.

Dominance is valid only for states with equivalent future possibilities, including terminal, visit status, ticket obligations, and relevant history. Earlier arrival is not automatically better when maximum waits, visit rules, or other timing constraints differ. Prove pruning conditions with small exhaustive reference cases.

Budget/time lower bounds must be optimistic. An estimate that overstates remaining cost must not prune feasible trips. Do not use a static shortest path as the final solution, or treat “go home immediately” as a valid zero-visit optimum.

For tiny fixed datasets, maintain an exhaustive reference solver used only in tests. Compare feasible sets and best scores against the production search. Larger instances may use bounded/approximate search, but must disclose incompleteness. “Best among retrieved candidates” is different from globally optimal travel availability.

### Constraint relaxation

Never silently relax limits. If there are no matches, explain whether budget, return window, connectivity, coverage, or search limits contributed. Offer a concrete modified request, such as a wider return window, for user selection. Do not claim that a constraint is the sole cause unless the search establishes it.

## 7. Ignav live integration

Use `docs/api_references/ignav/openapi.json` as the checked-in contract. This plan does not assume that the deployed service, commercial terms, quotas, or retention permissions have been verified.

| Existing contract operation | Planned role |
| --- | --- |
| `/api/health` | Provider health signal; not proof that a particular route can be searched |
| `/api/airports` | Airport lookup and mapping input; not a complete canonical city registry |
| `/api/fares/one-way` | Independently purchasable directional journey candidates |
| `/api/fares/round-trip` | Complete simple round-trip candidates |
| `/api/fares/search` | One or two ordered flight legs; do not assume arbitrary multi-city support |
| `/api/fares/cheapest-dates` | Date exploration hints; obtain complete offers before itinerary construction |
| `/api/fares/booking-links` | Booking handoff for supported offers; not inventory reservation |

Implement the client in infrastructure behind an application-owned provider port. Reuse generated models for boundary validation, with separate normalized planner models. Configuration must include provider base URL, server-side credentials, timeout policy, concurrency/call budget, and cache policy; document names without real secrets when implementation begins.

- Honor endpoint-specific statuses: malformed requests, authentication/permission failures, payment/quota conditions, rate limiting, dependency failures, and unavailability must remain distinguishable.
- Retry only eligible transient failures, with bounded backoff and a total deadline. Confirm duplicate-request billing and retry semantics before retrying paid searches automatically.
- Never retry invalid input or invalid credentials as if transient. Respect documented retry hints where supplied.
- Cancel work when no longer useful, prevent identical concurrent searches from multiplying provider calls, and avoid exhaustive all-city/all-date fan-out.
- Cache keys include every provider-affecting parameter: endpoints, dates, traveler basis, bags, cabin, market, filters, and adapter/schema version.
- Treat no fares as a successful empty response only when the provider actually completed the request. Do not cache failures as empty inventory.
- Track observation time separately from retrieval time and expiry. Freshness policy is configurable and must follow provider terms.
- Preserve opaque IDs and source references. Handle expired/missing booking IDs, changed prices, absent links, and changed availability as user-visible recoverable states.

The current generated provider price model uses numeric amounts and the domain adapter retains floats. Plan a deliberate money migration: inspect raw numeric token handling, normalize at the boundary into Decimal, retain original payload evidence if allowed, and test exact output. Converting an already-rounded float cannot recover precision. Do not alter the provider schema merely to pretend it supplies a different wire type.

## 8. Buses, trains, ferries: source-selection workstream

Use **Mobility Database for GTFS Schedule feed discovery and snapshot acquisition** for covered bus, rail, and ferry operators. Accept individual feeds only after coverage, service dates, rights and quality checks. This is a planned catalog/schedule source; commercial fare, inventory and booking providers remain unselected. Investigate authorized operator feeds, commercial aggregators and regional partners for those missing capabilities.

The local [OpenAPI reference](docs/api_references/mobilitydatabase/openapi.yml) defines catalog endpoints and metadata, not the CSV schema inside each archive. [IMPLEMENTATION.md, section 3.5](IMPLEMENTATION.md#35-mobility-database-exact-data-requirements) specifies the API operations, exact metadata, GTFS tables, graph derivation and acceptance tests. The [official GTFS Schedule reference](https://gtfs.org/documentation/schedule/reference/) defines table semantics.

### Mobility Database data to acquire

| Need | Data to retain | Application use |
| --- | --- | --- |
| Find relevant feeds | Paginated `/v1/gtfs_feeds`; country/location/bounding filters; feed ID, provider, status, official/seasonal flags, redirects | Select reviewed geographic coverage; classify modes from archive route types, not feed names |
| Pin accepted datasets | `latest_dataset.id`; dataset detail/history; `hosted_url`, SHA-256 `hash`, `downloaded_at`, service-date range, validation metadata | Immutable snapshot manifest and reproducible refreshes; date ranges require actual calendar checks |
| Establish rights | `source_info` producer/access/license metadata and license detail where available | Traceability, permitted storage/display, attribution and retention |
| Build terminals and topology | `agency.txt`, `stops.txt`, `routes.txt`, `trips.txt`, `stop_times.txt` | Map feed-local stops to canonical cities; derive directed connections from ordered trips, retaining terminal pairs and internal stops |
| Add dated schedules/durations | Stop times plus `calendar.txt` and/or `calendar_dates.txt`; `frequencies.txt` when used | Actual operating days, departure/arrival instants and durations as overlays; account for overnight times, timezones and exceptions |
| Validate transfers | `transfers.txt`, station hierarchy, `pathways.txt`/`levels.txt` when supplied, additional access/boarding evidence | Feasible terminal changes; missing transfer data never means zero transfer time |
| Optional published fares | Fare V1/V2 tables plus all referenced rule tables when present | Separate tariff evidence; not guaranteed live quotes, inventory or historical quote samples |
| Later disruptions | Linked GTFS-RT feed metadata and supported realtime entities | Cancellation/delay overlay after the static schedule slice works |

Mobility Database is not the canonical city gazetteer: retain the city's independent identity layer and map stops to it. Basic rail/bus/ferry route types map to application modes; review extended types and unsupported urban/on-demand services explicitly. Flights remain an Ignav integration with separate route evidence.

For the first import, require the scheduling core and a valid calendar representation; preserve optional fares, frequency, transfer and geometry files without claiming unsupported capabilities. A missing fare remains unknown and can use the historical-estimate workflow in [ALGORITHM.md](ALGORITHM.md). Timetable durations are scheduled evidence, not permanent graph weights.

Current acquisition tooling downloads latest European snapshots for all statuses and preserves raw tables; it does not implement production feed acceptance or semantic normalization. Reconcile its geography with the base graph, retain immutable versioned archives, prevent duplicate regional/national sources, and keep deprecated/development data out of ordinary searches. Select versions by actual service coverage, not simply newest download time. Do not claim complete intercity coverage from catalog discovery.

### Remaining provider selection

Evaluate each candidate with the same scorecard:

| Criterion | Questions and acceptance evidence |
| --- | --- |
| Coverage | Which countries, operators, routes, terminals, service dates, and modes are actually covered? |
| Schedule quality | Timezones, service calendars, overnight services, cancellations, connections, updates? |
| Price/inventory | Exact fare or estimate? Party basis? Mandatory fees? Seat availability? Expiry? |
| Ticket semantics | Through-ticket versus separate purchases? Restrictions? Reservation requirements? |
| Booking | Stable handoff links or supported booking flow? Revalidation available? |
| Identity | Reliable station/port IDs and mappings? Multi-terminal city handling? |
| Rights | Commercial display, storage, caching, redistribution, attribution, and retention permissions? |
| Operations | Authentication, quotas, request cost, sandbox, latency, outages, schema changes? |
| Accessibility | Available boarding/accessibility information and its reliability? |

Conduct one small corridor spike per mode. Produce a coverage report, normalized fixture, request-cost estimate, licensing assessment, and failure-mode test before selecting a provider.

Mode-specific concerns: trains may require separate reservations and through-fares; buses may use curbside stops and station changes; ferries may have seasonal service, boarding cutoffs, vehicle/passenger distinctions, and compulsory accommodation. Start with foot-passenger ferries if selected; vehicle travel requires a new traveler contract.

Providers advertise capabilities independently: schedule lookup, priced offer search, availability, booking links, revalidation. Schedule-only integrations can support a clearly labeled exploration view later, but must not be mixed into fully priced budget-compliant results. Missing a mode's provider should produce explicit coverage information, not fabricated edges.

## 9. Money, totals, and data provenance

- Use exact Decimal amounts in normalized planning models and decimal strings in shared JSON contracts. Validate currency codes, nonnegative values, and finite amounts.
- Retain original offer currency. Proposed first live milestone: only compare offers already in the requested budget currency; report excluded currency coverage.
- Before cross-currency support, select an FX source and define rate timestamp, expiry, conversion direction, precision, rounding, and whether converted totals are estimates. Keep rates fixed for a search snapshot.
- Sum purchase units once, including required transfer fares and mandatory fees when known. Unknown mandatory costs prevent a fully verified total.
- Preserve distinction between quoted, estimated, unverified, stale, unavailable, and synthetic data. Do not collapse provider-specific status semantics without a documented mapping.
- Store source, observation timestamp, transformation version, original identifiers, and freshness state with each offer. Synthetic fixture provenance must survive API serialization and rendering.
- Document baggage defaults and one-adult scope. The mock generator's party totals and USD prices must not be rendered as live EUR per-adult prices.

## 10. Application architecture and storage

Proposed responsibilities, within existing folders:

| Layer | Responsibilities |
| --- | --- |
| `domain/` | Location, money, schedule, transfer, visit, offer, itinerary, constraint, and score value objects/invariants |
| `application/` | Normalize search, acquire candidates, solve round trips, rank, validate final itineraries, revalidate handoff; own ports |
| `infrastructure/ignav/` | Live client, boundary models, response normalization, error translation |
| Other `infrastructure/` adapters | Future providers, location catalog, offer/cache repositories, clock, FX, metrics |
| `infrastructure/graphs/` | Connectivity projections and schedule indexes; no transport handlers |
| `presentation/` | CLI and future HTTP/GraphQL composition, input translation, safe error responses |
| Frontend | Form state, request lifecycle, accessible result comparison and handoff |

Application ports should reflect actual needs: city lookup, journey-offer search, transfer lookup, offer revalidation, clock, cache/storage, and exchange rates when implemented. Avoid a single provider interface that pretends every mode supports every operation.

Begin solver development with in-memory repositories and deterministic fixtures. For a live service, persist the canonical location catalog and mapping versions; cache offers and searches with controlled retention. Keep per-search graph snapshots reproducible and independent of concurrent cache changes.

Choose a transactional database after specifying deployment, concurrency, migration, retention, and backup needs. DuckDB's presence is not a decision to use it as the production transactional store. Likewise, a graph database is not required merely because routing uses a graph. Avoid adding a queue or distributed cache before bounded synchronous searches are measured; introduce background jobs if observed latency requires them.

## 11. Shared API evolution

Keep `shared/graphql/schema_v1.graphql` authoritative. The existing code generation emits models/types only. Select an executable GraphQL implementation compatible with the existing service stack in an implementation spike; do not create a divergent REST contract accidentally.

First implement v1 validation and semantics against fixture-backed application use cases. Then design an explicit extension/version for richer search:

- Ferry mode and supported-mode/coverage discovery.
- Preference profile, sort order, visit requirements, transfer limits, and result limits.
- Search envelope: ID, status, results, coverage, provider warnings, truncation, and timestamps.
- Itinerary/offer identities, terminal details, local zones, transfer/visit breakdowns, cost completeness, ticket grouping, score explanation, and handoff capability.
- Structured validation errors distinct from provider failure, partial data, and valid complete empty results.
- Optional asynchronous lifecycle only when needed: submitted, acquiring, solving, complete, partial, failed, cancelled, expired; explicit polling/cancellation behavior.

The current bare list cannot express partial coverage adequately. Do not hide an outage behind an empty list or retrofit weighted ranking under a documented price-first query. Keep v1 as a compatibility facade where feasible; otherwise document migration before connecting consumers.

Schema work must update input validation, serializers, domain mappings, generated outputs, fixtures, previews, frontend consumers, and contract tests together. Preserve alias `from`, RFC 3339 timestamp offsets, and Decimal string mappings. Regenerate instead of editing generated files.

## 12. User experience plan

Build on `CityPicker`, `TripInputs`, `TripOpportunities`, existing shadcn/ui primitives, Base UI conventions, theme tokens, and Lucide icons. This is a product behavior plan, not a new visual design or component implementation.

### Input flow

1. Select canonical home city and travel dates.
2. Enter transport budget and currency; clearly state the one-adult basis.
3. Choose required/excluded cities and available modes.
4. Set return flexibility and visit requirements; use explicit units and clear zero behavior.
5. Optionally adjust preference profile and advanced limits.
6. Review normalized dates/window and submit.

The current calendar date plus duration is ambiguous relative to the API's earliest-departure and target-return instants. Decide whether duration means nights or calendar days, which home-local time is the return target, and how date-only input maps to windows. Show the resulting window before search; do not silently interpret local midnight as UTC or assume every day has 24 hours.

### Results and states

- Show route, city visit time, transport burden, trip duration, total/basis/currency, modes, and tradeoffs.
- Expand a timeline containing terminals, local date/time and timezone, connections, independent ticket boundaries, and boarding buffers.
- Display “Cheapest,” “Least travel time,” and “Balanced” only when supported by actual comparisons.
- Expose freshness and coverage summaries; distinguish live, estimated, stale, and demo results.
- Handle idle, validating, loading, progressive/partial, empty, provider failure, cancellation, expired offer, changed price, and successful handoff.
- Prevent stale responses from replacing newer searches; preserve inputs on failure and allow deliberate retry.
- Provide accessible labels, keyboard operation, focus management, status announcements, error associations, and reduced-motion behavior. Verify narrow screens, long city names, and both themes.
- Keep previews as component examples; production pages must not import preview sample results as live data.

Accounts and saved searches are not prerequisites for the first functional planner. A map can be added after the itinerary flow works; it must not substitute for an accessible ordered itinerary.

## 13. Reliability, security, and operating limits

- Keep provider credentials server-side; validate external data at ingress and redact request secrets and personal information from logs.
- Apply server-side input and complexity limits, concurrency quotas, deadlines, and rate limiting to protect paid provider access. Do not trust frontend-only bounds.
- Configure provider hosts; do not let user input determine arbitrary backend fetch URLs. Validate booking URL schemes and allowed handoff destinations.
- Record correlated search/provider IDs, response categories, cache hits, provider calls/cost where known, candidate counts, expanded/pruned states, truncation causes, and stage latency.
- Measure empty-result rate separately from provider-failure rate. Monitor stale-offer/price-change rates and coverage by mode/region.
- Define retention and deletion policies for searches and raw responses before persistence; retain only what terms and privacy requirements permit.
- Use reproducible search snapshots for debugging without retaining credentials or unnecessary traveler data.
- Proposed initial product targets, to validate by benchmark: acknowledge submission promptly, complete bounded fixture searches within an interactive budget, and bound live searches by an explicit server deadline. Set numerical latency/cost SLOs after measuring provider performance; do not promise unsupported throughput.

## 14. Delivery phases and acceptance gates

| Phase | Work and dependencies | Exit evidence |
| --- | --- | --- |
| 0 — Semantics | Resolve launch scope, visit semantics, date conversion, tolerance/ranking separation, and one-adult budget policy | Written decisions and representative accepted/rejected itineraries; no ambiguous defaults hidden in UI |
| 1 — Domain foundation | Canonical city/terminal mapping, exact money, scheduled journeys, purchase units, transfer policies, ferry enum migration design | Unit/contract tests for invariants; existing architecture and graph tests remain valid |
| 2 — Offline solver | Deterministic feasible fixtures, bounded offer-aware search, independent validator, ranking and explanations | Exhaustive-oracle agreement on small graphs; no double-counted fares or infeasible connections; deterministic limits |
| 3 — Fixture API and UI | Implement API contract, schema evolution, real request lifecycle, input normalization, result states, frontend test setup | Browser journey submits constraints and receives validated fixture results explicitly labeled synthetic |
| 4 — Live Ignav | Client, mapping/catalog, provider error policy, cache/call bounds, real offer provenance, handoff revalidation | Opt-in staging checks plus offline failure tests; complete live flight round trip without preview data |
| 5 — First non-flight source | Import accepted Mobility Database GTFS for one corridor, normalize stops/calendars/transfers, attach schedule overlays; select a fare/inventory source using the scorecard | Calendar-correct, provenance-traceable routing first; real multimodal round trip only with complete cost and transfer evidence; unsupported capabilities visible |
| 6 — Additional modes | Repeat source gate for remaining bus/train/ferry sources; mode-specific conditions | Tested supported corridors per mode; no claim of universal coverage |
| 7 — Launch hardening | Load measurements, observability, security controls, retention, deployment/rollback runbook | Numerical budgets established, operational drills passed, documented known limitations |

Source discovery can proceed alongside phases 1–4, but does not block the flight-only milestone. Search correctness precedes scale optimization. Do not assign delivery dates until provider access, team capacity, and launch scope are known.

### First implementation slice

After approving semantics, create a tiny deterministic home → required city → home dataset with two alternative offers per direction and known terminals. Implement normalization, feasibility, purchase totals, and price-first ordering through the existing application layers. Include a missed connection and a bundled-fare trap. Expose it through the chosen API and existing form before expanding route discovery or adding live-provider fan-out.

## 15. Decision register

These are implementation gates, not decisions silently made by this document.

| Decision | Proposed starting point | Resolve before |
| --- | --- | --- |
| Launch geography/horizon | Small measured coverage region and bounded dates | Provider acquisition and performance commitments |
| Meaning of a visit | Explicit city visit with minimum stay; transfers do not count | Solver state and input contract |
| No required cities | Discover at least one destination under bounded candidate policy | Discovery UX and solver completion rules |
| Duration/date semantics | Home-local calendar intent converted to visible departure/return windows | Form-to-API integration |
| Return to origin | Same canonical city; terminal changes explicitly modeled | Feasibility implementation |
| Intermediate home returns/revisits | First home return ends trip; other revisits allowed only within bounds | Search pruning rules |
| Tolerance and ranking | Preserve existing hard limits; add separate preferences | Schema extension |
| Budget inclusions | One adult, mandatory transport costs; exclude accommodation/activities | Public totals and labels |
| Initial currency | Only requested-currency quotes until an FX policy is approved | Live price comparison |
| Transfer uncertainty | Exclude from verified results; optionally show separate exploratory estimates | Multimodal launch |
| Non-flight sources | Mobility Database for accepted GTFS topology/schedules; select remaining fare/inventory/booking sources per corridor using section 8 | Each mode's live implementation |
| Ignav terms and limits | Verify credentials, quotas, billing, retry/cache rights, deployed contract | Live client activation |
| API/database choices | Compatibility spikes, then minimal measured implementation | Service/persistence infrastructure |
| Preference scales/defaults | Versioned and explainable, tested against example trips | Balanced ranking launch |
| Trip protections | Preserve known/unknown status; no inferred guarantees | Booking handoff |

## 16. Verification strategy and completion criteria

### Automated coverage to add with implementation

- **Domain:** reversed/naive timestamps, DST transitions, overnight/date-line travel, exact return boundaries, zero tolerance, zero/unknown money, incompatible currencies, duplicate and conflicting city constraints, unknown mappings, and ferry inclusion.
- **Feasibility:** same-city different-terminal transfers, exact minimum connection boundary, missed boarding cutoffs, unavailable transfers, excluded internal offer connections, required-city stays, repeated cities, and no feasible return.
- **Fare correctness:** parallel offers, duplicate/missing provider IDs, multi-segment and round-trip bundles charged once, incomplete bundle rejection, fees/baggage uncertainty, party basis, Decimal serialization, and FX rounding when introduced.
- **Solver:** exhaustive small-graph oracle, deterministic ties, safe dominance/pruning, disconnected routes, empty schedules, static connectivity without temporal reachability, search caps, and truthful incomplete-result metadata.
- **Properties:** on a fixed complete candidate set, relaxing budget/window cannot remove feasible itineraries; changing ranking weights cannot mutate raw facts. Capped acquisition/search need not exhibit this monotonicity and must disclose limits.
- **Providers:** successful/empty/malformed responses, nullable fields, aliases, timeouts, cancellation, status translation, retry bounds, cache isolation, expiry, and booking price changes. Ordinary tests use mocked network boundaries.
- **API:** full cross-field validation, error/empty/partial distinctions, schema round trips, mode completeness, Decimal strings, timestamp offsets, and deterministic generated output.
- **Frontend:** form validation and submission, date normalization, preference changes, response races, loading/empty/error/partial states, accurate price badges, accessibility and keyboard interaction, long content, mobile layouts, and themes.
- **Performance:** fixed-seed datasets, bounded label/call growth, memory/candidate limits, and benchmark reports; avoid fragile elapsed-time unit assertions.
- **Architecture:** preserve stdlib-only core boundaries and existing regression coverage; no provider models imported into the domain.

Use the backend's existing unittest conventions. Establish minimal React Testing Library-compatible component testing and a focused browser journey suite when frontend behavior is implemented; choose compatible versions then. Read installed Next.js docs and use Context7 for library/API-specific implementation decisions. No dependency installation is required for this planning document.

### Validation commands during implementation

Run focused tests first, then affected suites from the repository root:

- `uv run --project backend --locked python -m unittest discover -s backend/tests -v`
- `bun run --cwd frontend lint`
- `bun run --cwd frontend tsc --noEmit`
- `bun run --cwd frontend build`
- New frontend component/browser test commands once configured; lint/build do not replace them.
- `just codegen` for shared contract changes; `just codegen-ignav` for provider model inputs/configuration changes. Inspect drift and verify deterministic regeneration.
- `just preview` for visual review where useful; previews supplement automated tests.
- `git diff --check` and final scope review.

Use `mise exec --` when tools are not on PATH. Keep Bun/uv manifests and lockfiles synchronized. Live integration checks must be explicitly opt-in, credentialed, bounded in cost, and excluded from ordinary offline suites.

### Definition of a usable first live release

A user can enter supported constraints, receive a genuinely time-feasible flight round trip from Ignav with an exact and correctly scoped quoted total, understand the tradeoff and freshness, and reach a valid provider handoff when available. No itinerary uses synthetic data unknowingly, invents a missing connection, violates hard constraints, or splits a bundled fare into fictitious tickets. Failures and limited coverage are visible. Remaining transport modes have documented source decisions or remain clearly unavailable.

A full multimodal release additionally requires verified source coverage and transfer feasibility for buses, trains, and ferries in the advertised geography; having enum values or synthetic graph edges is insufficient.
