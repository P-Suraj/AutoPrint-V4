"""Price calculation. Pure functions: no I/O, no clock, integer paise only.

Rate-card rules (stored in ap.rate_cards.rules):

    {
      "bw":    {"simplex": [SLAB, ...], "duplex": [SLAB, ...]},
      "color": {"simplex": [SLAB, ...], "duplex": [SLAB, ...]}
    }
    SLAB = {"from_sides": int >= 1, "to_sides": int | null, "paise_per_side": int >= 0}

Rule: total printed sides = selected pages x copies. The slab whose range contains that total
gives one rate, applied to every side of the job. (A "side" is one printed face of a sheet,
so a duplex sheet is two sides.) Amount = total sides x paise_per_side.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_COPIES = 100
# ASCII digits only (the "\\d" class also matches digits of other scripts, which int() accepts and a print program may
# not), and the plain space as the only white space: no tabs, no line breaks. The text ends up on a command line.
_RANGE_RE = re.compile(r"[0-9]{1,6}(-[0-9]{1,6})?( *, *[0-9]{1,6}(-[0-9]{1,6})?)*")


class PricingError(ValueError):
    """Raised for invalid user input or an invalid rate card. `code` is a key in app.errors.CATALOG."""

    def __init__(self, message: str, code: str = "invalid_items"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Price:
    selected_pages: int
    printed_sides: int
    paise_per_side: int
    amount_paise: int
    page_range: str | None = None      # the range in its one normal form (see normalise_pages); None = every page


def parse_page_range(page_range: str | None, page_count: int) -> list[int]:
    """Return the sorted, de-duplicated page numbers selected by a range like '1-3, 5, 8-9'."""
    if page_range is None or page_range.strip(" ") == "":
        return list(range(1, page_count + 1))
    text = page_range.strip(" ")
    if not _RANGE_RE.fullmatch(text):
        raise PricingError("Page range must look like 1-5, 8, 11-15", "invalid_page_range")
    pages: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            start_s, end_s = part.split("-")
            start, end = int(start_s), int(end_s)
        else:
            start = end = int(part)
        if start < 1 or end < start or end > page_count:
            raise PricingError(f"Page range must stay between 1 and {page_count}", "invalid_page_range")
        pages.update(range(start, end + 1))
    return sorted(pages)


def normalise_pages(pages: list[int]) -> str:
    """The one way a set of pages is written: ascending, no repeats, no spaces, runs joined: [1, 2, 3, 5] -> '1-3,5'.
    This, never the customer's own text, is what is stored and handed to the print program, so what is printed is
    exactly what was priced ('1,1,1' is priced as one page and must print as one page)."""
    runs: list[str] = []
    start = prev = None
    for n in pages:
        if prev is not None and n == prev + 1:
            prev = n
            continue
        if start is not None:
            runs.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = n
    if start is not None:
        runs.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(runs)


def validate_rules(rules: dict) -> None:
    """Reject a rate card that could produce a wrong or missing price."""
    for color in ("bw", "color"):
        for sides in ("simplex", "duplex"):
            try:
                slabs = rules[color][sides]
            except (KeyError, TypeError):
                raise PricingError(f"Rate card is missing {color}.{sides}", "no_rate_card") from None
            if not isinstance(slabs, list) or not slabs:
                raise PricingError(f"Rate card {color}.{sides} needs at least one slab", "no_rate_card")
            expected_from = 1
            for i, slab in enumerate(slabs):
                if not isinstance(slab, dict):
                    raise PricingError(f"Rate card {color}.{sides} slab {i + 1} must be an object", "no_rate_card")
                lo, hi, rate = slab.get("from_sides"), slab.get("to_sides"), slab.get("paise_per_side")
                if not (isinstance(lo, int) and isinstance(rate, int)) or isinstance(lo, bool) or isinstance(rate, bool):
                    raise PricingError(f"Rate card {color}.{sides} slab {i + 1} must use whole numbers", "no_rate_card")
                if lo != expected_from or rate < 0:
                    raise PricingError(f"Rate card {color}.{sides} slabs must start at 1 and leave no gaps", "no_rate_card")
                last = i == len(slabs) - 1
                if last:
                    if hi is not None:
                        raise PricingError(f"Rate card {color}.{sides}: the last slab must have no upper limit", "no_rate_card")
                else:
                    if not isinstance(hi, int) or isinstance(hi, bool) or hi < lo:
                        raise PricingError(f"Rate card {color}.{sides} slab {i + 1} has an invalid upper limit", "no_rate_card")
                    expected_from = hi + 1


def price_job(*, page_count: int, copies: int, color: bool, duplex: bool,
              page_range: str | None, rules: dict) -> Price:
    if not isinstance(copies, int) or isinstance(copies, bool) or not 1 <= copies <= MAX_COPIES:
        raise PricingError(f"Copies must be between 1 and {MAX_COPIES}", "invalid_copies")
    if page_count < 1:
        raise PricingError("Document has no pages")
    validate_rules(rules)
    pages = parse_page_range(page_range, page_count)
    selected = len(pages)
    whole_document = page_range is None or page_range.strip(" ") == ""
    sides = selected * copies
    slabs = rules["color" if color else "bw"]["duplex" if duplex else "simplex"]
    rate = next(s["paise_per_side"] for s in slabs if s["to_sides"] is None or sides <= s["to_sides"])
    return Price(selected_pages=selected, printed_sides=sides, paise_per_side=rate, amount_paise=sides * rate,
                 page_range=None if whole_document else normalise_pages(pages))


def format_rupees(paise: int) -> str:
    """Display only. 600 -> '₹6', 650 -> '₹6.50'."""
    rupees, rem = divmod(paise, 100)
    return f"₹{rupees}" if rem == 0 else f"₹{rupees}.{rem:02d}"
