"""Writes contracts/pricing_vectors.json: inputs with the amounts the Python pricing module produces.
The web app's TypeScript estimator is tested against the same file, so the two cannot drift silently."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.pricing import PricingError, price_job  # noqa: E402

RULES = {
    "bw": {"simplex": [{"from_sides": 1, "to_sides": 9, "paise_per_side": 200}, {"from_sides": 10, "to_sides": None, "paise_per_side": 150}],
           "duplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 120}]},
    "color": {"simplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 1000}],
              "duplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 800}]},
}
CASES = [
    (3, 1, False, False, None), (3, 3, False, False, None), (3, 4, False, False, None), (9, 1, False, False, None),
    (10, 1, False, False, None), (3, 1, False, True, None), (3, 1, True, False, None), (3, 2, True, True, None),
    (10, 1, False, False, "2-4"), (10, 1, False, False, "1-3, 2, 5"), (10, 1, False, False, "1,1,1"),
    (10, 10, False, False, "1-5"), (1, 100, False, False, None), (5, 1, False, False, "  "),
    (10, 1, False, False, "0"), (10, 1, False, False, "11"), (10, 1, False, False, "3-1"), (10, 1, False, False, "1-"),
    (10, 1, False, False, "a"), (3, 0, False, False, None), (3, 101, False, False, None),
]
out = []
for pages, copies, color, duplex, rng in CASES:
    case = {"page_count": pages, "copies": copies, "color": color, "duplex": duplex, "page_range": rng}
    try:
        p = price_job(page_count=pages, copies=copies, color=color, duplex=duplex, page_range=rng, rules=RULES)
        case.update(expect={"selected_pages": p.selected_pages, "printed_sides": p.printed_sides,
                            "paise_per_side": p.paise_per_side, "amount_paise": p.amount_paise})
    except PricingError as exc:
        case.update(expect={"error": exc.code})
    out.append(case)
(ROOT / "contracts" / "pricing_vectors.json").write_text(json.dumps({"rules": RULES, "cases": out}, indent=2) + "\n", encoding="utf-8", newline="\n")
print("wrote", len(out), "cases")
