export type Maybe<T> = T | null;
export type InputMaybe<T> = Maybe<T>;
/** All built-in and custom scalars, mapped to their actual values */
export type Scalars = {
  ID: { input: string; output: string; }
  String: { input: string; output: string; }
  Boolean: { input: boolean; output: boolean; }
  Int: { input: number; output: number; }
  Float: { input: number; output: number; }
  /** An RFC 3339 timestamp with an explicit UTC offset, such as 2026-12-01T09:00:00Z. */
  DateTime: { input: string; output: string; }
  /** An exact, non-negative decimal encoded as a JSON string, such as \"149.95\". */
  Decimal: { input: string; output: string; }
};

/**
 * A city marker in WGS 84 decimal degrees, suitable for an OpenStreetMap overlay.
 * Coordinates represent the city centre, not a terminal or a vehicle position.
 */
export type City = {
  __typename?: 'City';
  /**
   * Canonical application city identifier, matching the corresponding leg endpoint.
   * This identifier is not an OpenStreetMap node ID or a globally universal ID.
   */
  id: Scalars['ID']['output'];
  /** Finite WGS 84 latitude in the inclusive range [-90, 90]. */
  latitude: Scalars['Float']['output'];
  /** Finite WGS 84 longitude in the inclusive range [-180, 180]. */
  longitude: Scalars['Float']['output'];
  name: Scalars['String']['output'];
};

export type CityAttractivenessInput = {
  /** Canonical city identifier, distinct and neither home nor excluded. */
  city: Scalars['String']['input'];
  /** Finite strictly positive relative weight. Unspecified cities use 1. */
  weight: Scalars['Float']['input'];
};

export type CityStay = {
  __typename?: 'CityStay';
  attractiveness: Scalars['Float']['output'];
  city: Scalars['String']['output'];
  /**
   * Approximate target seconds, proportional to attractiveness after travel time.
   * Based on target return capped by maximum duration, excluding initial home waiting.
   */
  target_time: Scalars['Float']['output'];
  /**
   * Actual elapsed seconds between arrival and next departure, summed over revisits.
   * Includes internal connections; does not guarantee usable sightseeing time.
   */
  time_spent: Scalars['Float']['output'];
};

export type Money = {
  __typename?: 'Money';
  /** Non-negative amount expressed in major currency units. */
  amount: Scalars['Decimal']['output'];
  /** Uppercase ISO 4217 currency code, matching the search budget currency. */
  currency: Scalars['String']['output'];
};

export type MoneyInput = {
  /** Non-negative amount expressed in major currency units. */
  amount: Scalars['Decimal']['input'];
  /** Uppercase ISO 4217 currency code, such as USD or EUR. */
  currency: Scalars['String']['input'];
};

export type Query = {
  __typename?: 'Query';
  /**
   * Find round-trip itineraries satisfying the supplied constraints.
   * By default results are ordered by total price, then movement time.
   * With fuzzy_search, weighted city-stay fit ranks first, then price and movement time.
   * Hard schedule, city, budget and return-window constraints always apply.
   */
  round_trip_options: Array<RoundTripOption>;
};


export type QueryRound_Trip_OptionsArgs = {
  input: RoundTripSearchInput;
};

export type RoundTripOption = {
  __typename?: 'RoundTripOption';
  city_stays: Array<CityStay>;
  /**
   * Non-empty list of legs in chronological order. The first leg starts and
   * the last leg ends in departure_city. Each leg starts where the previous
   * leg ended, no earlier than its arrival time. All legs use allowed modes.
   */
  path: Array<TripLeg>;
  /**
   * Fuzzy similarity in [0, 1], higher is better; null for price-first searches.
   * One minus summed absolute stay error divided by actual plus target stay time.
   * Zero when no time is available or spent in cities.
   */
  stay_fit?: Maybe<Scalars['Float']['output']>;
  /** Total price for one adult, including taxes and mandatory fees. */
  total_price: Money;
};

export type RoundTripSearchInput = {
  /** Soft attractiveness weights; not verified tourism ratings. */
  city_attractiveness?: Array<CityAttractivenessInput>;
  /** Non-empty canonical city identifier; also the final destination. */
  departure_city: Scalars['String']['input'];
  /**
   * Earliest permitted departure timestamp from departure_city.
   * Despite the field name, this is a timestamp, not a calendar date.
   */
  departure_date: Scalars['DateTime']['input'];
  /**
   * Target return arrival timestamp at departure_city, strictly after departure_date.
   * Despite the field name, this is a timestamp, not a calendar date.
   */
  desired_arrival_date: Scalars['DateTime']['input'];
  /**
   * Distinct canonical city identifiers that must not occur as leg endpoints,
   * including connections. Must not overlap mandatory_cities or departure_city.
   */
  excluded_cities?: Array<Scalars['String']['input']>;
  /**
   * Maximum total itinerary price, inclusive of taxes and mandatory fees.
   * This is an absolute budget, not a percentage or an amount above a baseline.
   */
  expenses_tolerance: MoneyInput;
  /**
   * Prefer approximate attractiveness-weighted stays instead of price-first ranking.
   * No exact per-city stay is required; infeasible schedules are never relaxed.
   */
  fuzzy_search?: Scalars['Boolean']['input'];
  /**
   * Distinct canonical city identifiers that must each be visited at least once.
   * Their order does not constrain the itinerary. Must not contain departure_city.
   */
  mandatory_cities?: Array<Scalars['String']['input']>;
  /**
   * Hard elapsed limit in seconds from departure_date, including initial waiting.
   * Positive when supplied; intersected with the return window.
   */
  max_trip_duration?: InputMaybe<Scalars['Int']['input']>;
  /**
   * Maximum absolute deviation, in minutes, of the final return arrival from
   * desired_arrival_date. Must be non-negative; zero requires an exact match.
   * This tolerance does not permit departure before departure_date.
   */
  time_tolerance: Scalars['Int']['input'];
  /** Non-empty list of distinct allowed transport modes. */
  transport_types: Array<TransportType>;
};

/** Supported transport modes. A search may allow more than one mode. */
export type TransportType =
  | 'BUSSES'
  | 'FERRIES'
  | 'PLANES'
  | 'TRAINS';

export type TripLeg = {
  __typename?: 'TripLeg';
  /** Arrival timestamp, strictly after departure_at. */
  arrival_at: Scalars['DateTime']['output'];
  departure_at: Scalars['DateTime']['output'];
  /** Canonical departure city identifier. */
  from: Scalars['String']['output'];
  /** Departure city marker; from_city.id must equal from. */
  from_city: City;
  /**
   * Travel duration in whole seconds, equal to arrival_at minus departure_at.
   * Does not include waiting time before or after this leg.
   */
  time_in_travel: Scalars['Int']['output'];
  /** Canonical arrival city identifier. */
  to: Scalars['String']['output'];
  /** Arrival city marker; to_city.id must equal to. */
  to_city: City;
  transport_type: TransportType;
};
