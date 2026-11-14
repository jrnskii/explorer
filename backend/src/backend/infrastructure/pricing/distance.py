"""Graph distance features and route-balanced log-price regressions."""

from collections import defaultdict
from decimal import Decimal
import json
import math
from statistics import median

MIN_ROUTES = 3
BASIS = "city_centres_great_circle"


def valid_distance(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def scope(identity, ferry=False):
    parts = json.loads(identity)
    return json.dumps([parts[0]] if ferry else parts[2:], separators=(",", ":"))


def graph_distances(graph):
    """Keep directed mode-specific edges; ambiguity is excluded, never guessed."""
    from backend.infrastructure.pricing.forecast import code, name, route
    from backend.infrastructure.pricing.download import SCHENGEN

    nodes = {}
    aliases = defaultdict(set)
    for node, attrs in graph.nodes(data=True):
        if attrs.get("name") and attrs.get("country"):
            label = (name(attrs["name"]), code(attrs["country"]))
            nodes[node] = label
            aliases[label].add(node)
    from backend.infrastructure.catalog.static_transport import coordinates, distance_km

    unique = set()
    resolved_aliases = 0
    for label, candidates in aliases.items():
        if len(candidates) == 1:
            unique.update(candidates)
            continue
        canonical = [
            node
            for node in candidates
            if graph.nodes[node].get("source") == "Cities.csv"
        ]
        if len(canonical) != 1:
            continue
        preferred = canonical[0]
        point = coordinates(
            graph.nodes[preferred].get("latitude"),
            graph.nodes[preferred].get("longitude"),
        )
        nearby = [
            coordinates(
                graph.nodes[node].get("latitude"), graph.nodes[node].get("longitude")
            )
            for node in candidates
        ]
        # Source precedence only disambiguates nearby reference/station aliases of
        # the same normalized city and country, using the existing 10 km mapping radius.
        if point and all(p is not None and distance_km(point, p) <= 10 for p in nearby):
            unique.add(preferred)
            resolved_aliases += 1
    city_points = {}
    for node in unique:
        attrs = graph.nodes[node]
        point = coordinates(attrs.get("latitude"), attrs.get("longitude"))
        if point is not None:
            city_points[json.dumps(nodes[node], separators=(",", ":"))] = [
                point["latitude"],
                point["longitude"],
            ]
    pairs, ferry_segments = {}, defaultdict(dict)
    counts = defaultdict(int)
    counts["nearby_reference_alias_groups_resolved"] = resolved_aliases
    for origin, destination, attrs in graph.edges(data=True):
        mode, distance = attrs.get("mode"), attrs.get("distance_km")
        if mode not in ("PLANES", "TRAINS", "BUSSES", "FERRIES"):
            continue
        if not valid_distance(distance) or attrs.get("distance_basis") != BASIS:
            counts["invalid_or_unsupported_distance"] += 1
            continue
        if origin not in unique or destination not in unique:
            counts["ambiguous_or_missing_endpoint"] += 1
            continue
        a, b = nodes[origin], nodes[destination]
        if a[1] not in SCHENGEN or b[1] not in SCHENGEN:
            continue
        identity = (mode, origin, destination)
        if identity not in pairs:
            pairs[identity] = distance
        elif pairs[identity] != distance:
            pairs[identity] = None
        if mode == "FERRIES" and attrs.get("feed_id") and attrs.get("route_id"):
            fare_id = json.dumps(
                [attrs["feed_id"], attrs["route_id"], "", ""], separators=(",", ":")
            )
            ferry_segments[fare_id][(origin, destination)] = pairs[identity]
    result = {mode: {} for mode in ("PLANES", "TRAINS", "BUSSES", "FERRIES")}
    for (mode, origin, destination), distance in pairs.items():
        if distance is None:
            counts["conflicting_parallel_distance"] += 1
            continue
        a, b = nodes[origin], nodes[destination]
        result[mode][route(a[0], b[0], a[1], b[1])] = distance
    # A flat ferry product can cover several graph segments. Use one route-level
    # median segment length for fitting only; serving keeps known flat fares intact.
    ferry_routes = {
        r: median(pairs[("FERRIES", *pair)] for pair in values)
        for r, values in ferry_segments.items()
        if values and all(pairs[("FERRIES", *pair)] is not None for pair in values)
    }
    return dict(
        edges=result,
        cities=city_points,
        ferry_routes=ferry_routes,
        diagnostics=dict(counts),
    )


def resolve_distance(features, mode, identity):
    direct = features.get("edges", {}).get(mode, {}).get(identity)
    if direct is not None:
        return direct, "base_graph_edge"
    if identity is None:
        return None, None
    parts = json.loads(identity)
    if len(parts) != 4:
        return None, None
    a = features.get("cities", {}).get(
        json.dumps([parts[0], parts[2]], separators=(",", ":"))
    )
    b = features.get("cities", {}).get(
        json.dumps([parts[1], parts[3]], separators=(",", ":"))
    )
    if a is None or b is None:
        return None, None
    from backend.infrastructure.catalog.static_transport import distance_km

    return (
        distance_km(
            dict(latitude=a[0], longitude=a[1]), dict(latitude=b[0], longitude=b[1])
        ),
        "base_graph_city_centres",
    )


def _fit(units):
    if len(units) < MIN_ROUTES or len({u["distance_km"] for u in units}) < 2:
        return None
    xs = [math.log1p(u["distance_km"]) for u in units]
    ys = [math.log1p(float(u["price"])) for u in units]
    xbar, ybar = sum(xs) / len(xs), sum(ys) / len(ys)
    variance = sum((x - xbar) ** 2 for x in xs)
    if variance <= 1e-12:
        return None
    slope = max(
        0.0,
        sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys, strict=True)) / variance,
    )
    intercept = ybar - slope * xbar
    residuals = [y - intercept - slope * x for x, y in zip(xs, ys, strict=True)]
    dates = sorted(
        d for u in units for d in (u.get("evidence_start"), u.get("evidence_end")) if d
    )
    return dict(
        intercept=intercept,
        slope=slope,
        min_km=min(u["distance_km"] for u in units),
        max_km=max(u["distance_km"] for u in units),
        samples=len(units),
        residual_min=min(0.0, min(residuals)),
        residual_max=max(0.0, max(residuals)),
        evidence_start=dates[0] if dates else None,
        evidence_end=dates[-1] if dates else None,
    )


def predict_distance(model, distance):
    if (
        not model
        or model.get("enabled") is False
        or not valid_distance(distance)
        or not model["min_km"] <= distance <= model["max_km"]
    ):
        return None
    value = model["intercept"] + model["slope"] * math.log1p(distance)
    amount = lambda residual: str(max(0.0, math.expm1(value + residual)))
    return dict(
        value=amount(0),
        lower=amount(model["residual_min"]),
        upper=amount(model["residual_max"]),
        samples=model["samples"],
        evidence_start=model.get("evidence_start"),
        evidence_end=model.get("evidence_end"),
    )


def fit_distance(entries, distances, ferry=False):
    """Each route is one unit, independent of months, seats or parallel edges."""
    groups = defaultdict(list)
    mapped = 0
    for identity, entry in sorted(entries.items()):
        distance = distances.get(identity)
        if not valid_distance(distance):
            continue
        mapped += 1
        entry["distance_km"] = distance
        baseline = entry["baseline"]
        groups[scope(identity, ferry)].append(
            dict(
                route=identity,
                distance_km=distance,
                price=Decimal(baseline["value"]),
                evidence_start=baseline.get("evidence_start"),
                evidence_end=baseline.get("evidence_end"),
            )
        )
    fitted = {}
    for group, units in sorted(groups.items()):
        model = _fit(units)
        if model is None:
            continue
        errors, baseline_errors = [], []
        folds = min(5, len(units))
        for fold in range(folds):
            training = [u for i, u in enumerate(units) if i % folds != fold]
            held = [u for i, u in enumerate(units) if i % folds == fold]
            candidate = _fit(training)
            baseline = median([u["price"] for u in training]) if training else None
            for unit in held:
                predicted = predict_distance(candidate, unit["distance_km"])
                if predicted is not None:
                    errors.append(abs(Decimal(predicted["value"]) - unit["price"]))
                    baseline_errors.append(abs(baseline - unit["price"]))
        mae = sum(errors) / len(errors) if errors else None
        baseline_mae = sum(baseline_errors) / len(baseline_errors) if errors else None
        # Do not enable a distance fallback that loses to its held-out scope median.
        model["enabled"] = mae is not None and mae <= baseline_mae
        model["validation"] = dict(
            split="deterministic_route_grouped_folds",
            purpose="model_selection_diagnostic_not_independent_test",
            test_routes=len(units),
            supported_routes=len(errors),
            mae_eur=str(mae) if mae is not None else None,
            scope_median_mae_eur=(
                str(baseline_mae) if baseline_mae is not None else None
            ),
        )
        fitted[group] = model
    return dict(
        groups=fitted,
        mapped_routes=mapped,
        unmapped_routes=len(entries) - mapped,
        target="published_product_or_tariff" if ferry else "route_baseline",
        distance_basis=BASIS,
        minimum_routes=MIN_ROUTES,
    )


def validate_distance_model(data):
    """Validate executable coefficients and support limits in a serving artifact."""
    for model in data.get("groups", {}).values():
        values = [
            model[k]
            for k in (
                "intercept",
                "slope",
                "min_km",
                "max_km",
                "residual_min",
                "residual_max",
            )
        ]
        if (
            any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
            or model["slope"] < 0
            or not 0 <= model["min_km"] < model["max_km"]
            or not model["residual_min"] <= 0 <= model["residual_max"]
            or type(model["samples"]) is not int
            or model["samples"] < MIN_ROUTES
            or type(model["enabled"]) is not bool
        ):
            raise ValueError("Invalid distance regression artifact")
        try:
            for distance in (model["min_km"], model["max_km"]):
                value = model["intercept"] + model["slope"] * math.log1p(distance)
                if not math.isfinite(math.expm1(value + model["residual_max"])):
                    raise ValueError("Invalid distance regression prediction range")
        except OverflowError as error:
            raise ValueError("Invalid distance regression prediction range") from error
