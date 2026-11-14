"""Offline staging with estimated fares and explicitly synthetic schedules."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from hashlib import sha256

from backend.application.round_trip_search import SearchLimits, find_round_trips
from backend.domain.planning import JourneyOffer, Money, SearchSettings, TripLeg
from backend.domain.travel import TransportType
from backend.domain.pricing import ForecastQuery
from backend.infrastructure.pricing.forecast import load_forecaster

COUNTRIES = dict(Vilnius="LT", Warsaw="PL", Berlin="DE", Paris="FR", Amsterdam="NL")

CITIES = ("Vilnius", "Warsaw", "Berlin", "Paris", "Amsterdam")


def mock_scrappa_search(origin, destination, day, mode, travelers):
    """Scrappa/Omio price-floor response shape, never a live quote.

    Ferry is a separate synthetic extension: Scrappa's Omio endpoint does not
    support ferry. Floors are used only under this explicit demo policy.
    """
    key = f"{origin}:{destination}:{day}:{mode}".encode()
    cents = (1500 + int(sha256(key).hexdigest()[:8], 16) % 3500) * travelers
    return {
        "success": True,
        "data": {
            "trip_type": "one_way",
            "price_floor_per_mode": {mode: {"amount_minor": cents, "currency": "USD"}},
        },
        "meta": {"billable": False, "synthetic": True},
    }


def search(
    departure="Vilnius",
    departure_date=None,
    duration=5,
    budget=200,
    travelers=1,
    modes=tuple(TransportType),
    must_visit=(),
    avoid=(),
    return_date=None,
    days_per_city=0,
    number_of_cities=0,
    pricing="forecast",
    forecaster=None,
    as_of=None,
):
    departure_date = departure_date or date.today()
    if pricing not in ("forecast", "mock"):
        raise ValueError("Pricing must be forecast or mock.")
    as_of = as_of or date.today()
    if pricing == "forecast":
        forecaster = forecaster or load_forecaster()
        if departure_date < as_of:
            raise ValueError("Forecast departure cannot precede the information date.")
    if not 1 <= duration <= 14 or not 1 <= travelers <= 9:
        raise ValueError("Duration must be 1–14 days; travelers must be 1–9.")
    if days_per_city < 0 or number_of_cities < 0:
        raise ValueError("City count and stay days cannot be negative.")
    if not {departure, *must_visit, *avoid} <= set(CITIES):
        raise ValueError("Choose cities from the demo catalog.")
    start = datetime.combine(departure_date, time(), timezone.utc)
    deadline = start + timedelta(days=duration)
    target = (
        datetime.combine(return_date, time(23, 59), timezone.utc)
        if return_date
        else deadline
    )
    if return_date and return_date < departure_date:
        raise ValueError("Return date cannot precede departure.")
    # Date-only return means any arrival that day. Without one, duration is a cap.
    tolerance = 1439 if return_date else duration * 1440
    settings = SearchSettings(
        departure,
        start,
        target,
        tolerance,
        Money(Decimal(str(budget)), "EUR" if pricing == "forecast" else "USD"),
        tuple(modes),
        tuple(must_visit),
        tuple(avoid),
        duration * 86400,
    )
    offers = []
    mode_names = {
        TransportType.PLANES: "flight",
        TransportType.TRAINS: "train",
        TransportType.BUSSES: "bus",
        TransportType.FERRIES: "ferry",
    }
    for offset in range(duration + 1):
        day = departure_date + timedelta(days=offset)
        for origin in CITIES:
            for destination in CITIES:
                if origin == destination:
                    continue
                for mode in modes:
                    name = mode_names[mode]
                    if pricing == "forecast":
                        prediction = forecaster.predict(
                            ForecastQuery(
                                mode,
                                origin,
                                destination,
                                day,
                                as_of,
                                COUNTRIES[origin],
                                COUNTRIES[destination],
                                travelers,
                            )
                        )
                        if prediction is None:
                            continue
                        price = prediction.price
                        source = "forecast:" + prediction.model_id
                    else:
                        payload = mock_scrappa_search(
                            origin, destination, day, name, travelers
                        )
                        raw_price = payload["data"]["price_floor_per_mode"][name]
                        price = Money(
                            Decimal(raw_price["amount_minor"]) / 100,
                            raw_price["currency"],
                        )
                        source = (
                            "synthetic-ferry" if name == "ferry" else "mock-scrappa"
                        )
                    depart = datetime.combine(day, time(8), timezone.utc)
                    leg = TripLeg(
                        origin, destination, depart, depart + timedelta(hours=2), mode
                    )
                    offers.append(
                        JourneyOffer(
                            f"{origin}:{destination}:{day}:{name}",
                            (leg,),
                            price,
                            source,
                            True,
                        )
                    )
    # Retain all candidates within the state cap before applying UI-only filters.
    result = find_round_trips(
        settings, offers, SearchLimits(max_states=500, max_results=500)
    )
    options = tuple(
        option
        for option in result.options
        if (not number_of_cities or len(option.city_stays) == number_of_cities)
        and all(stay.time_spent >= days_per_city * 86400 for stay in option.city_stays)
    )
    return options[:20], result


def build_widgets(*, pricing="forecast", forecaster=None, as_of=None):
    import ipywidgets as w
    from IPython.display import display

    controls = {
        "departure": w.Dropdown(options=CITIES, description="Departure"),
        "departure_date": w.DatePicker(value=date.today(), description="Date"),
        "duration": w.BoundedIntText(value=5, min=1, max=14, description="Days"),
        "budget": w.BoundedIntText(
            value=200,
            min=0,
            max=100000,
            description="Budget EUR" if pricing == "forecast" else "Budget USD",
        ),
        "travelers": w.BoundedIntText(value=1, min=1, max=9, description="Travelers"),
        "modes": w.SelectMultiple(
            options=[(m.value, m) for m in TransportType],
            value=tuple(TransportType),
            description="Modes",
        ),
        "number_of_cities": w.BoundedIntText(
            value=0, min=0, max=4, description="City count"
        ),
        "return_date": w.DatePicker(description="Return date"),
        "days_per_city": w.BoundedIntText(
            value=0, min=0, max=14, description="Stay days"
        ),
        "must_visit": w.SelectMultiple(options=CITIES, description="Must visit"),
        "avoid": w.SelectMultiple(options=CITIES, description="Avoid"),
    }
    output = w.Output()

    def update(change=None):
        with output:
            output.clear_output(wait=True)
            try:
                if controls["departure_date"].value is None:
                    raise ValueError("Select a departure date.")
                options, result = search(
                    **{key: widget.value for key, widget in controls.items()},
                    pricing=pricing,
                    forecaster=forecaster,
                    as_of=as_of,
                )
                print(
                    "Estimated EUR fares; synthetic schedules; no booking availability. Unsupported routes are omitted."
                    if pricing == "forecast"
                    else "SYNTHETIC ONLY — mock Scrappa prices; invented schedules; no booking availability."
                )
                print(
                    f'{result.states_explored} states; truncation: {result.truncation_reasons or "none"}'
                )
                if not options:
                    print(
                        "No supported priced matches in this bounded schedule search."
                    )
                for option in options:
                    print(
                        " → ".join(
                            [option.path[0].origin]
                            + [leg.destination for leg in option.path]
                        ),
                        f"{option.total_price.currency} {option.total_price.amount}",
                        option.path[-1].arrival_at.isoformat(),
                    )
            except ValueError as exc:
                print(f"Check inputs: {exc}")

    for widget in controls.values():
        widget.observe(update, names="value")
    panel = w.VBox(
        [
            w.HTML(
                "<b>Offline staging demo</b><br>UTC dates. City count 0 = any; stay days 0 = no minimum. Flexible dates are unavailable in this fixed-window demo."
            ),
            w.Checkbox(
                value=False, description="Flexible dates (unsupported)", disabled=True
            ),
            *controls.values(),
            output,
        ]
    )
    update()
    return panel, controls, output
