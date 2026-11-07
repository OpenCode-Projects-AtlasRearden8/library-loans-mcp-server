"""Tests for the pure loan logic: due-date math, status, renewals."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from library_loans.loans import (
    DEFAULT_LOAN_DAYS,
    MAX_RENEWALS,
    Loan,
    LoanError,
    check_renewal,
    compute_default_due,
    loan_status,
    parse_date,
)
from library_loans.store import LoanStore

TODAY = date(2026, 11, 7)


def make_loan(due: date, renewals: int = 0, returned: date | None = None) -> Loan:
    return Loan(
        id="L-1",
        title="Test Book",
        author="",
        branch="Northgate",
        checked_out=due - timedelta(days=DEFAULT_LOAN_DAYS),
        due=due,
        renewals=renewals,
        returned=returned,
    )


class TestParseDate:
    def test_accepts_iso(self) -> None:
        assert parse_date("2026-11-15") == date(2026, 11, 15)

    def test_surrounding_whitespace_is_fine(self) -> None:
        assert parse_date("  2026-11-15 ") == date(2026, 11, 15)

    def test_rejects_garbage_readably(self) -> None:
        with pytest.raises(LoanError, match="not a date we understand"):
            parse_date("11/15/2026")

    def test_rejects_non_string(self) -> None:
        with pytest.raises(LoanError, match="YYYY-MM-DD"):
            parse_date(20261115)  # type: ignore[arg-type]

    def test_rejects_impossible_dates(self) -> None:
        with pytest.raises(LoanError):
            parse_date("2026-13-40")


class TestDefaultDue:
    def test_default_is_checkout_plus_loan_days(self) -> None:
        checkout = date(2026, 11, 1)
        assert compute_default_due(checkout, DEFAULT_LOAN_DAYS) == date(2026, 11, 22)

    def test_nonstandard_lengths(self) -> None:
        assert compute_default_due(date(2026, 11, 1), 14) == date(2026, 11, 15)

    def test_rejects_zero_or_negative_lengths(self) -> None:
        with pytest.raises(LoanError, match="at least 1 day"):
            compute_default_due(date(2026, 11, 1), 0)
        with pytest.raises(LoanError):
            compute_default_due(date(2026, 11, 1), -7)


class TestLoanStatus:
    def test_overdue_when_due_is_before_today(self) -> None:
        assert loan_status(make_loan(TODAY - timedelta(days=1)), TODAY) == "overdue"

    def test_due_today_is_due_soon_not_overdue(self) -> None:
        assert loan_status(make_loan(TODAY), TODAY) == "due_soon"

    def test_within_window_is_due_soon(self) -> None:
        assert loan_status(make_loan(TODAY + timedelta(days=6)), TODAY) == "due_soon"

    def test_custom_window_for_due_soon(self) -> None:
        assert loan_status(make_loan(TODAY + timedelta(days=14)), TODAY, due_soon_days=15) == "due_soon"

    def test_beyond_window_is_on_time(self) -> None:
        assert loan_status(make_loan(TODAY + timedelta(days=8)), TODAY) == "on_time"
        assert loan_status(make_loan(TODAY + timedelta(days=30)), TODAY) == "on_time"

    def test_returned_state_wins(self) -> None:
        loan = make_loan(TODAY - timedelta(days=20), returned=TODAY - timedelta(days=1))
        assert loan_status(loan, TODAY) == "returned"


class TestRenewal:
    def test_renewal_extends_from_due_not_today(self) -> None:
        loan = make_loan(TODAY + timedelta(days=3))
        new_due = check_renewal(loan, TODAY, [], days=14)
        assert new_due == loan.due + timedelta(days=14)

    def test_cannot_renew_overdue_loan(self) -> None:

        loan = make_loan(TODAY - timedelta(days=2))
        with pytest.raises(LoanError, match="overdue"):
            check_renewal(loan, TODAY, [])

    def test_renewals_capped(self) -> None:

        loan = make_loan(TODAY + timedelta(days=3), renewals=MAX_RENEWALS)
        with pytest.raises(LoanError, match="out of renewals"):
            check_renewal(loan, TODAY, [])

    def test_at_cap_minus_one_renews(self) -> None:

        loan = make_loan(TODAY, renewals=MAX_RENEWALS - 1)
        assert check_renewal(loan, TODAY, []) == loan.due + timedelta(days=DEFAULT_LOAN_DAYS)

    def test_cannot_renew_returned_loan(self) -> None:

        loan = make_loan(TODAY + timedelta(days=3), returned=TODAY)
        with pytest.raises(LoanError, match="already returned"):
            check_renewal(loan, TODAY, [])

    def test_renewal_days_must_be_positive(self) -> None:

        loan = make_loan(TODAY + timedelta(days=3))
        with pytest.raises(LoanError, match="at least 1 day"):
            check_renewal(loan, TODAY, [], days=0)


class TestStoreDueDateLogic:
    def test_record_loan_defaults(self, fresh_store: LoanStore) -> None:
        loan = fresh_store.record_loan("Some Title", "A. Writer", "Westown")
        assert loan.checked_out == TODAY
        assert loan.due == TODAY + timedelta(days=DEFAULT_LOAN_DAYS)
        assert loan.id == "L-1"

    def test_record_loan_with_explicit_dates(self, fresh_store: LoanStore) -> None:
        loan = fresh_store.record_loan(
            "Some Title", "A. Writer", "Westown",
            checked_out="2026-10-01", due="2026-10-20",
        )
        assert loan.checked_out == date(2026, 10, 1)
        assert loan.due == date(2026, 10, 20)

    def test_due_before_checkout_rejected(self, fresh_store: LoanStore) -> None:
        with pytest.raises(LoanError, match="before the checkout"):
            fresh_store.record_loan("X", "", "Northgate",
                                    checked_out="2026-11-05", due="2026-11-01")

    def test_due_without_checkout_rejected(self, fresh_store: LoanStore) -> None:
        with pytest.raises(LoanError, match="also tell us the checked_out"):
            fresh_store.record_loan("X", "", "Northgate", due="2026-11-20")

    def test_renew_bumps_due_from_current_due(self, fresh_store: LoanStore) -> None:
        loan = fresh_store.record_loan("Thinking, Fast and Slow", "D. Kahneman", "Westown",
                                       checked_out="2026-11-01", due="2026-11-22")
        renewed = fresh_store.renew_loan(loan.id, days=21)
        assert renewed.due == date(2026, 12, 13)
        assert renewed.renewals == 1

    def test_renewal_survives_reload(self, tmp_path, fresh_store: LoanStore) -> None:
        loan = fresh_store.record_loan("Atomic Habits", "J. Clear", "Northgate",
                                       checked_out="2026-11-01", due="2026-11-22")
        fresh_store.renew_loan(loan.id)
        reloaded = LoanStore(tmp_path / "loans.json")
        reloaded._today = lambda: TODAY
        assert reloaded.find_loan(loan.id).renewals == 1
        assert reloaded.find_loan(loan.id).due == date(2026, 12, 13)

    def test_return_then_renew_refused(self, fresh_store: LoanStore) -> None:
        loan = fresh_store.record_loan("Duplicate Case", "", "Northgate")
        fresh_store.return_loan(loan.id)
        with pytest.raises(LoanError):
            fresh_store.renew_loan(loan.id)
