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
   * Results are ordered by total price, lowest first, then total travel time.
   */
  round_trip_options: Array<RoundTripOption>;
};


export type QueryRound_Trip_OptionsArgs = {
  input: RoundTripSearchInput;
};

export type RoundTripOption = {
  __typename?: 'RoundTripOption';
  /**
   * Non-empty list of legs in chronological order. The first leg starts and
   * the last leg ends in departure_city. Each leg starts where the previous
   * leg ended, no earlier than its arrival time. All legs use allowed modes.
   */
  path: Array<TripLeg>;
  /** Total price for one adult, including taxes and mandatory fees. */
  total_price: Money;
};

export type RoundTripSearchInput = {
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
   * Distinct canonical city identifiers that must each be visited at least once.
   * Their order does not constrain the itinerary. Must not contain departure_city.
   */
  mandatory_cities?: Array<Scalars['String']['input']>;
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
  /**
   * Travel duration in whole seconds, equal to arrival_at minus departure_at.
   * Does not include waiting time before or after this leg.
   */
  time_in_travel: Scalars['Int']['output'];
  /** Canonical arrival city identifier. */
  to: Scalars['String']['output'];
  transport_type: TransportType;
};
