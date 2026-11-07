"""Shared fixtures: a temp store and a frozen 'today' so tests are reproducible.

All fixture data is synthetic - no personal data, ever.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from library_loans.store import LoanStore

TODAY = date(2026, 11, 7)


@pytest.fixture
def fresh_store(tmp_path: Path) -> LoanStore:
    store = LoanStore(tmp_path / "loans.json")
    store._today = lambda: TODAY
    return store


@pytest.fixture
def busy_store(tmp_path: Path) -> LoanStore:
    """A store with loans spread across due states and a few holds."""
    store = LoanStore(tmp_path / "loans.json")
    store._today = lambda: TODAY
    store.record_loan("The Hidden Life of Trees", "Peter Wohlleben", "Northgate",
                      checked_out="2026-10-01", due="2026-11-01")  # overdue
    store.record_loan("Project Hail Mary", "Andy Weir", "Northgate",
                      checked_out="2026-10-25", due="2026-11-10")  # due in 3 days
    store.record_loan("The Beach Club", "Unknown Author", "Westown",
                      checked_out="2026-10-25", due="2026-11-10")
    store.record_loan("Spaceman", "Mike Massimino", "Westown",
                      checked_out="2026-10-30", due="2026-12-01")  # fine
    store.record_loan("Old Rambling Essays", "Anon", "Northgate",
                      checked_out="2026-09-01", due="2026-10-15")  # returned already
    store.return_loan("L-5", returned_on="2026-10-14")
    store.place_hold("Beyond Mars", "Northgate")  # waiting
    store.place_hold("Quiet Country", "Westown")
    store.update_hold("H-2", "ready")
    return store
