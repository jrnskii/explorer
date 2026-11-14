# Recursive round-trip discovery with historical price estimates

Status: algorithm specification, not an implementation. Complements [PLAN.md](PLAN.md). No application code is included.

## 1. Goal and interpretation

Starting from the user's desired city, inspect all known outgoing connections using selected transport types. Recursively repeat this process from each reachable city, estimating connection prices from previously observed prices stored in the database. Stop exploring branches that cannot fit within the maximum trip duration. Collect routes that return to the starting city, then spend live price requests on promising complete candidates.

In this document, “desired city” means the departure/home city because the application plans round trips. If the user also specifies a destination to visit, represent it as a mandatory city while keeping home as the start and finish.

“Every possible connection” means every connection in the available route catalog for the selected modes, geography, and date horizon. The algorithm cannot discover services absent from its sources or guarantee worldwide completeness. Route discovery, schedule acquisition, historical price lookup, and live fare requests are separate operations; catalog or schedule acquisition may itself incur provider costs.

## 2. Inputs

| Input | Meaning |
| --- | --- |
| Starting city | Canonical city identifier; also the required final city |
| Selected transport types | Nonempty selection of planes, buses, trains, and ferries, subject to available source coverage |
| Departure time | Earliest permitted departure, with an explicit timezone/offset |
| Maximum trip duration | Positive elapsed-time limit, including travel, waiting, transfers, and city stays |
| Required cities, optional | Cities that must receive a qualifying visit before returning home |
| Excluded cities, optional | Cities that must not occur, including internal connections |
| Visit durations | Required minimum stays and any user-selected longer stays |
| Budget, optional | Ceiling for the actual transport total; estimated compliance is provisional |
| Return window, optional | Additional earliest/latest return constraints |
| Ranking preferences | Price/time preferences used to order candidates without changing underlying facts |
| Search resource limits | Maximum states, legs, candidates, runtime, and paid requests |

Define the search deadline as earliest permitted departure plus maximum trip duration. This proposal includes initial waiting within the requested search window, producing a fixed finite horizon. If the product instead measures duration from actual first departure, it must also specify a latest permitted departure to keep the search horizon bounded.

When a return window is supplied, intersect it with the duration deadline. A trip must satisfy both; increasing a ranking preference cannot override either.

The current shared schema does not have a dedicated maximum-duration input. Implementation will require explicit contract design rather than treating the existing return-time tolerance as the same parameter.

## 3. Data used by the algorithm

### 3.1 Route catalog

For each city, store or retrieve its known outgoing directed connections, transport types, associated terminals, source, coverage, and update time. Retain parallel connections: two flights, two operators, or different modes between the same cities are alternatives, not duplicates to collapse automatically.

An A → B connection does not establish a B → A connection. City-level adjacency is useful for discovery; terminals and schedules are needed to validate transfers.

### 3.2 Schedule information

Where available, retain departure/arrival instants, service dates, terminal identities, and boarding/transfer requirements. Expand services whose departure follows the current arrival plus required stay and transfer time.

When only approximate travel durations are available, the first pass produces provisional route candidates, not confirmed itineraries. A static connection and an estimated duration cannot prove that a service departs on the requested day. Schedule uncertainty must survive into the output until validation.

### 3.3 Historical price observations

Each observation should retain:

- Directed origin and destination, terminals where known, transport mode, and provider/operator.
- Actual service/travel date, observation timestamp, and source offer identity.
- Amount, currency, traveler basis, fare class, baggage/mandatory-fee scope, and availability/price status.
- Purchase scope: independent one-way journey or a bundled multi-journey offer.
- Provenance distinguishing real provider observations from synthetic fixtures.

Store observations, not just their average, so estimates can be recomputed, audited, and filtered. Re-reading a cached quote must not insert another independent observation. Provider failures and sold-out responses are not zero-price observations.

For a planning request, take a stable historical-data snapshot or cutoff time. New observations can inform a subsequent search without unpredictably changing averages midway through the current search.

## 4. Historical average estimator

### Baseline rule

For a connection, select comparable valid historical observations from the database:

**Estimated price = sum of comparable observed prices ÷ number of comparable observations.**

At minimum, comparison requires the same direction, mode, currency, traveler basis, and purchase scope. Refine by terminal pair and fare inclusions when these differ materially. Never average EUR and USD directly, or combine one-person fares with party totals.

Example: independently purchasable A → B train journeys with comparable prices of EUR 30, EUR 40, and EUR 50 yield an estimated price of EUR 40. This estimate does not guarantee an available EUR 40 ticket today.

Return the average together with sample count, observation age range, data cutoff, and dispersion when available. A one-sample estimate should not appear as reliable as a recent, well-supported estimate.

### No-history behavior

An empty observation set produces an unknown estimate, never zero. Keep the connection eligible for exploration when its other constraints permit it, but mark its estimated total incomplete. Unknown-price candidates can enter a separately budgeted live-lookup queue rather than disappearing from the network.

A broader mode/distance-based estimate is an optional future fallback and must be labeled as such; it is not the average of previous prices for the same connection.

### Bundled fare restriction

The repository's Ignav adapter preserves itinerary-level fares. Do not store a whole bundle's price as an independently purchasable price for each segment, divide it arbitrarily across segments, or sum it once per segment.

Average comparable complete one-way journey offers for an atomic journey estimate. Average round-trip bundles separately and evaluate them as complete offers. A connecting one-way flight can be one purchase unit with several internal segments; all internal cities and schedules still require validation.

## 5. Recursive search state

Each recursive branch carries its own state:

- Starting city, current city, and current terminal when known.
- Ordered route and selected service/journey alternatives.
- Earliest next departure time and accumulated elapsed trip duration.
- Estimated transport total plus unknown-price and uncertainty markers.
- Required cities already visited with sufficient stay time.
- Number of movements/transfers and history needed to apply revisit policies.
- Purchase-unit identities or obligations if coupled offers are supported.

Do not mutate a shared path or accumulated total across sibling branches. Historical data and the route catalog may be shared read-only within a search snapshot.

## 6. Algorithm, step by step

### Step 1 — Normalize and validate

Resolve the starting city, selected modes, date/time boundaries, and city constraints. Reject invalid duration, conflicting city lists, or an empty mode selection. Record unavailable source coverage explicitly.

Initialize the route at home with zero accumulated cost and no visits. This initial state is not itself a round trip.

### Step 2 — Obtain outgoing connections

Read all known connections leaving the current city under the selected transport types. Exclude disallowed cities and modes, checking the internal segments of journey offers too.

Resolve relevant terminals and departures within the remaining horizon. Where schedules are not yet known, retain the connection as provisional under an explicitly approximate timing model.

### Step 3 — Estimate each connection's price

Retrieve the matching historical mean from the database or a per-search aggregate cache. Attach confidence metadata and preserve unknown values.

Order branches by promising estimated price/time if desired. Ordering changes which candidates are explored first; it must not be described as removing expensive branches safely.

No live fare lookup is necessary merely to expand each graph edge. This is the primary paid-request saving.

### Step 4 — Calculate the next state

For each connection/service alternative:

1. Determine the earliest feasible departure after arrival, required city stay, transfer, and boarding processing.
2. Include waiting until the selected service, movement duration, and any required terminal change.
3. Compute the next arrival and elapsed time from the search's departure boundary.
4. Add the estimated cost once per independently purchasable unit; preserve an incomplete-total flag if a component is unknown.
5. Update visits only when the defined stay requirement is satisfied.

Avoid double-counting internal connection waits already included in an atomic journey's elapsed duration. Keep intentional visit time separate for ranking while still counting it toward the maximum trip duration.

### Step 5 — Apply stopping conditions

Stop expanding a branch when:

- Its next arrival exceeds the maximum-duration deadline or effective latest return.
- It violates a hard mode, city, transfer, or visit rule.
- No allowed directed route back home exists in the known catalog.
- A proven optimistic minimum time to return home exceeds the remaining time.
- It reaches an explicit leg/state/runtime limit.

Historical average prices are not lower bounds on actual prices. An estimated total above budget may be deprioritized or excluded in an explicitly approximate mode, but cannot safely prove that no affordable live itinerary exists. Likewise, typical travel duration is not a safe minimum duration for definitive pruning.

### Step 6 — Record a completed round trip

When a branch returns home after visiting at least one other city, check required visits and the return window. If satisfied, record a complete candidate with its route, estimated total, timing basis, and uncertainty.

The proposed initial rule is that the first return home ends that branch. A return that fails required-visit constraints is rejected rather than extended into another excursion. Previously visited non-home cities are skipped by default, including internal ticket connections. Visit history belongs to each itinerary, not the entire search, so alternative routes can still visit the same cities. Python callers can explicitly opt into revisits with `allow_city_revisits=True`; time and leg limits still apply.

### Step 7 — Recurse

For a valid non-home destination, recursively repeat steps 2–6 from that city using the updated state. After the recursive call finishes, continue exploring the current city's other connections.

Stop when all branches have been considered within scope, or a resource limit is reached. If limited, retain useful candidates and report that exploration was truncated.

### Step 8 — Rank and shortlist

Deduplicate equivalent service/purchase combinations without collapsing genuinely different schedules or tickets. Rank completed candidates by estimated price, travel burden, and the selected preference profile.

Maintain a separate treatment for candidates with unknown estimates. Return enough route and mode diversity that one stale cheap connection does not consume the entire validation budget.

### Step 9 — Validate selected candidates with live data

Use expensive provider requests only for a bounded shortlist, reusing already-fresh matching quotes where permitted. For flights, use Ignav; other modes require selected source adapters.

For each candidate:

1. Obtain actual dated offers and schedules for its purchase units.
2. Replace estimates with quoted prices and confirmed schedule facts.
3. Recompute transfers, visits, duration, return window, and total mandatory transport cost.
4. Reject or mark incomplete anything unavailable, infeasible, unpriced, or over the actual budget.
5. Store valid new price observations with provenance and deduplication.

A schedule change can invalidate later legs; replacing the price alone is insufficient. A candidate may require bounded re-search using the new departures rather than a local price substitution.

Continue to the next shortlisted candidate when validation fails, until enough results exist or the paid-request budget/deadline is exhausted. Re-rank using actual prices among validated candidates. Unvalidated candidates remain explicitly estimated; do not mix them into a “verified cheapest” claim.

## 7. Worked example

Assume home city A, train and bus selected, departure boundary at 08:00, maximum duration 12 hours, and a one-hour minimum visit in B or C. The deadline is 20:00.

The known schedules and historical estimates are:

| Journey | Schedule | Historical estimate |
| --- | --- | --- |
| A → B train | 08:00–10:00 | EUR 40 |
| A → C bus | 08:30–11:30 | EUR 25 |
| B → A train | 12:00–14:00 | EUR 45 |
| B → C bus | 11:30–13:00 | EUR 20 |
| C → A bus | 15:00–18:00 | EUR 30 |
| C → B train | 18:00–20:00 | EUR 35 |

Assume the listed city departures are compatible with known terminal transfers and boarding requirements; these must be checked in real searches.

- A → B → A finishes at 14:00, has six elapsed hours, and an estimated total of EUR 85.
- A → C → A finishes at 18:00, has ten elapsed hours including the initial wait, and an estimated total of EUR 55.
- A → B → C → A finishes at 18:00, allows the required stays, and has an estimated total of EUR 90.
- A → C → B reaches B at 20:00 with no time left to return home, so that branch cannot complete under the deadline.

The system might validate A → C → A first under price-first ranking. If actual offers total EUR 95, it should compare them with actual quotes for other shortlisted routes as its budget permits; an EUR 85 estimate does not prove that another route is cheaper.

## 8. Termination, cost, and completeness

With average branching factor b and maximum depth d, naive recursive exploration can grow on the order of b to the power d. Schedule alternatives and multiple terminals increase branching further. A historical price cache reduces paid fare requests, not the combinatorial cost of enumerating routes.

A maximum duration bounds depth only when each expansion advances time by a strictly positive amount and the schedule domain is finite. Explicit leg and state limits also guard against bad data, tiny loops, and excessive expansion. Do not allow zero-time recursive cycles.

Cache adjacency, historical aggregates, and schedule indexes per search or versioned dataset rather than repeating database reads at every branch. Shared subproblems may be reused only when their terminal, time, visit, and fare obligations are compatible.

Distinguish:

- Exhaustive exploration of a finite known graph and schedule snapshot.
- Exploration stopped by configured limits.
- Shortlist-only live validation, even when estimated exploration completed.
- Missing provider or route coverage.

The algorithm generally finds good candidates within its known data and request budget. It does not establish the globally cheapest available trip merely by sorting historical averages.

## 9. Output

Return a search summary containing scope, data cutoff, coverage, states explored, truncation reasons, and live-lookup budget usage.

For each candidate include:

- Ordered cities, modes, terminals, service dates, and visits.
- Total elapsed duration and timing status: scheduled/validated or approximate.
- Estimated total, currency, known-price subtotal where incomplete, and estimation metadata.
- Validated quoted total separately when available, observation time, and cost-completeness status.
- Constraint validation outcome, ranking explanation, and remaining uncertainty.
- Booking handoff only when supported by an actual eligible provider offer.

A valid complete empty search is distinct from an interrupted search, provider failure, missing price history, or unsupported coverage.

## 10. Relationship to the existing codebase

- `infrastructure/graphs/weighted_graph.py` can represent parallel static connections but does not provide this recursive scheduled search.
- `application/fare_graph.py` projects supplied fare searches; place future search orchestration in the application layer and its invariants in the domain.
- `infrastructure/ignav/fare_search.py` already normalizes supplied offers. Extend integration around this boundary rather than introducing provider models into the solver.
- Historical price storage, aggregate queries, live Ignav requests, and a timed round-trip solver are new work. The database schema/engine is not selected by this document.
- Existing mocks supply deterministic tests, but synthetic observations must never enter live-price averages.
- The shared schema currently lacks ferries, explicit maximum duration, and estimate/validation metadata. Evolve source contracts and regenerate consumers during implementation.

## 11. Suggestions

### Improve estimate relevance

Start with the requested arithmetic mean as a transparent baseline. Later compare it with recent-window means, recency weighting, medians, and robust outlier handling. Segment history by season, weekday, booking lead time, and fare inclusions when sample sizes support it. Publish which estimator and fallback were used; do not silently change the baseline.

Historical search results can be biased toward routes and fares previously queried. Record sampling context and evaluate estimate error against later live quotes rather than presenting the mean as an unbiased market price.

### Spend live requests strategically

Reserve some request budget for unknown or uncertain connections to avoid permanently ignoring new routes. Deduplicate overlapping candidate requests, reuse fresh quotes, and validate cheap/high-impact shared legs where useful. Confirm provider caching, billing, and retry rules before implementing this policy.

### Order exploration intelligently

Depth-first recursion is a clear baseline. Best-first expansion can prioritize promising partial routes under tight limits, while branch-and-bound can help only with valid optimistic bounds. Beam search can reduce work but explicitly sacrifices completeness. Benchmark alternatives on the same deterministic fixtures before choosing a more complex approach.

### Use safe return-time bounds

Precompute optimistic return durations on an allowed-mode graph to reject branches that cannot possibly return in time. These bounds must underestimate or equal the true remaining time. Keep terminal and transfer details in final feasibility checks even when the bound is city-based.

### Avoid confusing transit with a city visit

Require an explicit stay policy so cheap airport connections do not count as sightseeing. Allow users to specify longer stays, and include them in the elapsed-duration limit. This also prevents the optimizer from favoring meaningless rapid loops.

### Validate with adversarial small examples

Before live integration, test: no historical prices; mixed currencies; stale averages; one-way-only connectivity; a cheap but missed connection; a route arriving exactly at the deadline; DST transitions; repeated cities; a zero-time cycle; excluded internal flight connections; bundled fares; and a shortlist where the initially cheapest estimate becomes the most expensive actual offer.

Compare small exhaustive results with the recursive implementation, and verify that every reported validated itinerary passes an independent final validator. Keep paid-provider tests opt-in and use deterministic offline fixtures for ordinary validation.
