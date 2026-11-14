import userEvent from "@testing-library/user-event";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import {
  TripOpportunities,
  TripOpportunitiesPlaceholder,
} from "./trip-opportunities";
import { SAMPLE_OPTIONS } from "./trip-opportunities.preview";

describe("TripOpportunities", () => {
  test("shows city names instead of canonical IDs in summaries, tooltips and details", async () => {
    const user = userEvent.setup();
    const original = SAMPLE_OPTIONS[0];
    const ids: Record<string, string> = {
      Vilnius: "gn-593116",
      Riga: "gn-456172",
      Tallinn: "gn-588409",
    };
    const option = {
      ...original,
      path: original.path.map((leg) => ({
        ...leg,
        from: ids[leg.from_city.name],
        to: ids[leg.to_city.name],
        from_city: { ...leg.from_city, id: ids[leg.from_city.name] },
        to_city: { ...leg.to_city, id: ids[leg.to_city.name] },
      })),
    };
    const { container } = render(<TripOpportunities options={[option]} />);
    expect(screen.getAllByText("Vilnius")).toHaveLength(2);
    expect(
      screen.getByRole("list", { name: "Cities visited" }),
    ).toHaveTextContent("Riga");
    expect(screen.getByTitle("Bus: Vilnius to Riga")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/gn-\d+/);
    await user.click(screen.getByRole("button", { name: "Travel details" }));
    expect(screen.getByText(/in Riga/)).toBeVisible();
    expect(screen.getAllByText("Tallinn").length).toBeGreaterThan(1);
    expect(container.textContent).not.toMatch(/gn-\d+/);
    expect(container.querySelector('[title*="gn-"]')).toBeNull();
  });

  test("lists opportunities as a plain vertical list without flexbox", () => {
    render(<TripOpportunities options={SAMPLE_OPTIONS} />);
    const region = screen.getByRole("region", { name: "Travel opportunities" });
    const list = within(region)
      .getAllByRole("list")
      .find((l) => l.parentElement === region);
    expect(list).toBeDefined();
    expect(list).not.toHaveClass("flex", "flex-wrap");
    expect(list!.children).toHaveLength(SAMPLE_OPTIONS.length);
    for (const li of Array.from(list!.children)) {
      expect(li.tagName).toBe("LI");
      expect(li).not.toHaveClass("flex", "grow");
    }
  });

  test("Book is a split button whose dropdown toggles the travel details", async () => {
    const user = userEvent.setup();
    render(<TripOpportunities options={SAMPLE_OPTIONS.slice(0, 1)} />);
    expect(screen.getByRole("button", { name: "Book" })).toBeEnabled();
    const trigger = screen.getByRole("button", { name: "Travel details" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Riga", { selector: "li span" })).toBeNull();

    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getAllByText("Riga", { selector: "li span" })[0],
    ).toBeVisible();

    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  test("shows every visited city on the route without expanding details", () => {
    const multiCity = SAMPLE_OPTIONS.find((o) => o.path.length === 4)!;
    render(<TripOpportunities options={[multiCity]} />);
    const stops = screen.getByRole("list", { name: "Cities visited" });
    expect(
      within(stops)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["Amsterdam", "Paris", "Barcelona"]);
  });

  test("marks each leg on the route line with its transport type", () => {
    const mixed = SAMPLE_OPTIONS.find(
      (o) => o.path[1]?.transport_type === "TRAINS",
    )!;
    const { container } = render(<TripOpportunities options={[mixed]} />);
    const segments = Array.from(
      container.querySelectorAll('ol[aria-label="Cities visited"] > li[title]'),
    );
    expect(segments.map((s) => s.getAttribute("title"))).toEqual(
      mixed.path.map((l) => {
        const label = {
          PLANES: "Plane",
          TRAINS: "Train",
          BUSSES: "Bus",
          FERRIES: "Ferry",
        }[l.transport_type];
        return `${label}: ${l.from} to ${l.to}`;
      }),
    );
    for (const s of segments) expect(s.querySelector("svg")).not.toBeNull();
  });

  test("shows departure and return times and the price", () => {
    render(<TripOpportunities options={SAMPLE_OPTIONS.slice(0, 1)} />);
    expect(screen.getByText("07:00")).toBeInTheDocument();
    expect(screen.getByText("23:15")).toBeInTheDocument();
    expect(screen.getByText("Price per adult")).toBeInTheDocument();
    expect(screen.getByText("€89.90")).toBeInTheDocument();
  });

  test("reports an empty result without rendering grid items", () => {
    render(<TripOpportunities options={[]} />);
    expect(
      screen.getByText("No travel opportunities match your search"),
    ).toBeInTheDocument();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });

  test("placeholder uses the same plain list", () => {
    render(<TripOpportunitiesPlaceholder count={4} />);
    const list = screen.getByRole("list");
    expect(list).not.toHaveClass("flex", "flex-wrap");
    expect(list.children).toHaveLength(4);
  });
});

describe("TripOpportunities featured option", () => {
  test("highlights only the featured option with its label", () => {
    const { container } = render(
      <TripOpportunities
        options={SAMPLE_OPTIONS}
        featuredIndex={2}
        featuredLabel="Best match"
      />,
    );
    const featured = container.querySelectorAll('[data-featured="true"]');
    expect(featured).toHaveLength(1);
    expect(
      within(featured[0] as HTMLElement).getByText("Best match"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Best match")).toHaveLength(1);
  });

  test("keeps the Cheapest badge when nothing is featured", () => {
    const { container } = render(
      <TripOpportunities options={SAMPLE_OPTIONS} />,
    );
    expect(container.querySelector('[data-featured="true"]')).toBeNull();
    expect(screen.getByText("Cheapest")).toBeInTheDocument();
  });
});

test("merges estimated and scheduled routes in price order and limits the combined list to seven", () => {
  const estimates = Array.from({ length: 8 }, (_, index) => ({
    rank: index + 1,
    cities: ["Paris", "Berlin", "Rome", "Paris"].map((name) => ({
      id: name,
      name,
    })),
    departure_date: "2030-01-01",
    return_date: "2030-01-04",
    total_price: { amount: String(100 - index * 10), currency: "EUR" },
    transport_types: ["TRAINS" as const, "TRAINS" as const, "TRAINS" as const], schedule_source: "reference",
  }));
  render(
    <TripOpportunities
      options={SAMPLE_OPTIONS.slice(0, 1)}
      estimatedRoutes={estimates}
    />,
  );
  const region = screen.getByRole("region", { name: "Travel opportunities" });
  const list = within(region)
    .getAllByRole("list")
    .find((element) => element.parentElement === region)!;
  expect(list.children).toHaveLength(7);
  expect(list.children[0]).toHaveTextContent("€30");
  expect(list.children[6]).toHaveTextContent("€89.90");
  expect(within(region).getAllByText("Estimated price per adult")).toHaveLength(
    6,
  );
});

test("estimated cards use the demo timeline and keyboard details without fabricated times or booking", async () => {
  const user = userEvent.setup();
  render(
    <TripOpportunities
      options={[]}
      estimatedRoutes={[
        {
          rank: 1,
          cities: ["Paris", "Berlin", "Rome", "Paris"].map((name) => ({
            id: name,
            name,
          })),
          departure_date: "2030-01-01",
          return_date: "2030-01-04",
          total_price: { amount: "40.00", currency: "EUR" },
          transport_types: ["TRAINS" as const, "TRAINS" as const, "TRAINS" as const], schedule_source: "reference",
        },
      ]}
    />,
  );
  expect(screen.getByText("Cheapest")).toBeInTheDocument();
  expect(
    screen.getByRole("list", { name: "Cities visited" }),
  ).toHaveTextContent("Berlin");
  expect(screen.getByText("1 Jan")).toBeInTheDocument();
  expect(screen.getByText("4 Jan")).toBeInTheDocument();
  expect(screen.queryByText("00:00")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Unverified" })).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Book" }),
  ).not.toBeInTheDocument();
  const details = screen.getByRole("button", { name: "Travel details" });
  await user.tab();
  expect(details).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(details).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText(/not bookable availability/)).toBeInTheDocument();
  expect(
    screen.getByRole("list", { name: "Route details" }).children,
  ).toHaveLength(3);
  await user.keyboard("{Enter}");
  expect(details).toHaveAttribute("aria-expanded", "false");
});

test("keeps the provider-verified best option first after a live fare increase", () => {
  const verified = {
    ...SAMPLE_OPTIONS[0],
    total_price: { amount: "999.00", currency: "EUR" },
  };
  render(
    <TripOpportunities
      options={[verified]}
      verifiedIndex={0}
      estimatedRoutes={Array.from({ length: 7 }, (_, index) => ({
        rank: index + 2,
        cities: ["Paris", "Berlin", "Rome", "Paris"].map((name) => ({
          id: name,
          name,
        })),
        departure_date: "2030-01-01",
        return_date: "2030-01-04",
        total_price: { amount: String(10 + index), currency: "EUR" },
        transport_types: ["TRAINS" as const, "TRAINS" as const, "TRAINS" as const], schedule_source: "reference",
      }))}
    />,
  );
  const region = screen.getByRole("region", { name: "Travel opportunities" });
  const list = within(region)
    .getAllByRole("list")
    .find((element) => element.parentElement === region)!;
  expect(list.children).toHaveLength(7);
  expect(list.children[0]).toHaveTextContent("Exact price");
  expect(list.children[0]).toHaveTextContent("€999");
  expect(list.children[1]).toHaveTextContent("€10");
  expect(screen.queryByText("Cheapest")).not.toBeInTheDocument();
});

test("estimated routes show each planned transport type in the timeline and details", async () => {
  const user = userEvent.setup();
  render(<TripOpportunities options={[]} estimatedRoutes={[{
    rank: 1, cities: ["Paris", "Berlin", "Rome", "Paris"].map(name => ({ id: name, name })),
    departure_date: "2030-01-01", return_date: "2030-01-04",
    total_price: { amount: "30", currency: "EUR" }, schedule_source: "reference",
    transport_types: ["TRAINS", "PLANES", "BUSSES"],
  }]} />);
  expect(screen.getByTitle("Train: Paris to Berlin")).toBeInTheDocument();
  expect(screen.getByTitle("Plane: Berlin to Rome")).toBeInTheDocument();
  expect(screen.getByTitle("Bus: Rome to Paris")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Travel details" }));
  const details = screen.getByRole("list", { name: "Route details" });
  expect(within(details).getAllByRole("listitem").map(item => item.textContent)).toEqual([
    "TrainParisBerlin", "PlaneBerlinRome", "BusRomeParis",
  ]);
  expect(screen.getByRole("button", { name: "Unverified" })).toBeDisabled();
});

test.each([undefined, null])("older estimates render and expand without transport types (%s)", async (transport_types) => {
  const user = userEvent.setup();
  render(<TripOpportunities options={[]} estimatedRoutes={[{
    rank: 1, cities: ["Paris", "Berlin", "Rome", "Paris"].map(name => ({ id: name, name })),
    departure_date: "2030-01-01", return_date: "2030-01-04",
    total_price: { amount: "30", currency: "EUR" }, schedule_source: "reference", transport_types,
  }]} />);
  expect(screen.getByRole("list", { name: "Cities visited" })).toHaveTextContent("Berlin");
  await user.click(screen.getByRole("button", { name: "Travel details" }));
  expect(within(screen.getByRole("list", { name: "Route details" })).getAllByText("Transport unverified")).toHaveLength(3);
});
