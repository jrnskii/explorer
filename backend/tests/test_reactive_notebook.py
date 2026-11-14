import unittest
from datetime import date
from backend.presentation.notebooks.reactive import (
    search,
    mock_scrappa_search,
    build_widgets,
)


class ReactiveTests(unittest.TestCase):
    def test_defaults_and_reactivity(self):
        panel, controls, output = build_widgets(pricing="mock")
        self.assertEqual(controls["departure_date"].value, date.today())
        self.assertEqual(controls["duration"].value, 5)
        self.assertEqual(controls["budget"].value, 200)
        controls["budget"].value = 0
        panel.close()

    def test_prices_and_deadline(self):
        args = ("Vilnius", "Warsaw", date(2026, 1, 1), "train")
        a = mock_scrappa_search(*args, 1)
        b = mock_scrappa_search(*args, 2)
        self.assertEqual(
            b["data"]["price_floor_per_mode"]["train"]["amount_minor"],
            2 * a["data"]["price_floor_per_mode"]["train"]["amount_minor"],
        )
        options, result = search(pricing="mock", departure_date=date(2026, 1, 1))
        self.assertTrue(options)
        self.assertTrue(all(o.total_price.amount <= 200 for o in options))
        self.assertTrue(
            all(o.path[-1].arrival_at.date() <= date(2026, 1, 6) for o in options)
        )
        options, result = search(
            pricing="mock", departure_date=date(2026, 1, 1), duration=1
        )
        self.assertFalse(options)
        self.assertEqual(result.states_explored, 17)  # No day-two arrivals expanded.

    def test_invalid_and_empty(self):
        with self.assertRaises(ValueError):
            search(pricing="mock", modes=())
        with self.assertRaises(ValueError):
            search(pricing="mock", must_visit=("Warsaw",), avoid=("Warsaw",))
        self.assertTrue(search(pricing="mock", budget=0)[0])  # Legacy budget is advisory.
