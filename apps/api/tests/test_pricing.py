"""Worked pricing examples. These are the contract; docs/CONTRACTS.md quotes them."""
import pytest

from app.pricing import PricingError, format_rupees, parse_page_range, price_job, validate_rules

RULES = {
    "bw": {"simplex": [{"from_sides": 1, "to_sides": 9, "paise_per_side": 200},
                       {"from_sides": 10, "to_sides": None, "paise_per_side": 150}],
           "duplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 120}]},
    "color": {"simplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 1000}],
              "duplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 800}]},
}


def price(**kw):
    base = dict(page_count=3, copies=1, color=False, duplex=False, page_range=None, rules=RULES)
    base.update(kw)
    return price_job(**base)


def test_three_pages_bw_simplex_is_six_rupees():
    p = price()
    assert (p.selected_pages, p.printed_sides, p.paise_per_side, p.amount_paise) == (3, 3, 200, 600)
    assert format_rupees(p.amount_paise) == "₹6"


def test_copies_multiply_sides_and_can_cross_a_slab():
    assert price(copies=3).amount_paise == 9 * 200          # 9 sides: still the first slab
    assert price(copies=4).amount_paise == 12 * 150         # 12 sides: second slab applies to every side


def test_slab_boundaries():
    assert price(page_count=9).paise_per_side == 200
    assert price(page_count=10).paise_per_side == 150


def test_duplex_and_color_use_their_own_rates():
    assert price(duplex=True).amount_paise == 3 * 120
    assert price(color=True).amount_paise == 3 * 1000
    assert price(color=True, duplex=True, copies=2).amount_paise == 6 * 800


def test_page_range_selects_unique_pages_only():
    assert parse_page_range("1-3, 2, 5", 10) == [1, 2, 3, 5]
    assert price(page_count=10, page_range="2-4").amount_paise == 3 * 200
    assert price(page_count=10, page_range="1,1,1").selected_pages == 1
    assert parse_page_range(None, 4) == [1, 2, 3, 4] and parse_page_range("  ", 2) == [1, 2]


@pytest.mark.parametrize("bad", ["0", "1-", "-3", "a", "3-1", "1;2", "1,,2", "11", "1-11", "1 2"])
def test_invalid_page_ranges_are_refused(bad):
    with pytest.raises(PricingError):
        parse_page_range(bad, 10)


@pytest.mark.parametrize("copies", [0, -1, 101, 1.5, True, None])
def test_invalid_copies_are_refused(copies):
    with pytest.raises(PricingError):
        price(copies=copies)


def test_money_is_integer_paise_never_float():
    p = price(page_count=7)
    assert isinstance(p.amount_paise, int)
    assert format_rupees(650) == "₹6.50" and format_rupees(5) == "₹0.05" and format_rupees(0) == "₹0"


@pytest.mark.parametrize("mutate,why", [
    (lambda r: r["bw"].pop("duplex"), "missing duplex"),
    (lambda r: r["bw"]["simplex"].__setitem__(0, {"from_sides": 2, "to_sides": 9, "paise_per_side": 200}), "does not start at 1"),
    (lambda r: r["bw"]["simplex"].__setitem__(1, {"from_sides": 11, "to_sides": None, "paise_per_side": 150}), "gap"),
    (lambda r: r["bw"]["simplex"][1].__setitem__("to_sides", 20), "last slab bounded"),
    (lambda r: r["bw"]["simplex"][0].__setitem__("paise_per_side", -1), "negative"),
    (lambda r: r["bw"]["simplex"][0].__setitem__("paise_per_side", 2.5), "float rate"),
    (lambda r: r["color"].__setitem__("simplex", []), "empty"),
])
def test_invalid_rate_cards_are_refused(mutate, why):
    import copy
    rules = copy.deepcopy(RULES)
    mutate(rules)
    with pytest.raises(PricingError):
        validate_rules(rules)


def test_valid_rate_card_passes():
    validate_rules(RULES)
