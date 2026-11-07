"""Tests for the JSON store: ids, persistence, and graceful failure modes."""

from __future__ import annotations

import pytest

from library_loans.loans import LoanError, loan_status
from library_loans.store import LoanStore


class TestPersistence:
    def test_blank_file_created_on_first_use(self, fresh_store: LoanStore) -> None:
        assert fresh_store.path.exists()
        assert fresh_store.all_loans() == []
        assert fresh_store.all_holds() == []

    def test_ids_increase_across_kinds(self, fresh_store: LoanStore) -> None:
        a = fresh_store.record_loan("Book One", "", "Northgate")
        fresh_store.place_hold("Hold One", "Northgate")
        b = fresh_store.record_loan("Book Two", "", "Westown")
        assert (a.id, b.id) == ("L-1", "L-2")
        assert fresh_store.find_hold("H-1")[0].title == "Hold One"

    def test_roundtrip(self, tmp_path) -> None:
        store = LoanStore(tmp_path / "loans.json")
        loan = store.record_loan("Roundtrip", "W. Writer", "Northgate",
                                 checked_out="2026-10-01", due="2026-10-22")
        hold = store.place_hold("Sequel", "Westown")
        again = LoanStore(tmp_path / "loans.json")
        assert again.find_loan(loan.id).title == "Roundtrip"
        assert again.all_holds()[0].id == hold.id

    def test_missing_fields_rejected(self, tmp_path) -> None:
        import json

        path = tmp_path / "loans.json"
        path.write_text(json.dumps({"loans": [{"id": "L-1", "title": "Broken"}]}),
                        encoding="utf-8")
        with pytest.raises(LoanError, match="missing"):
            LoanStore(path)


class TestQueries:
    def test_due_soon_excludes_overdue_and_far(self, busy_store: LoanStore) -> None:
        soon = busy_store.due_soon()
        assert [loan.title for loan, _ in soon] == [
            "Project Hail Mary",
            "The Beach Club",
        ]

    def test_due_soon_window_must_be_positive(self, busy_store: LoanStore) -> None:
        with pytest.raises(LoanError, match="at least 1 day"):
            busy_store.due_soon(0)

    def test_overdue_only(self, busy_store: LoanStore) -> None:
        titles = [loan.title for loan in busy_store.overdue_loans()]
        assert titles == ["The Hidden Life of Trees"]

    def test_returned_loans_leave_active_list(self, busy_store: LoanStore) -> None:
        active = busy_store.active_loans()
        assert "Old Rambling Essays" not in [loan.title for loan in active]
        assert len(busy_store.all_loans()) == 5

    def test_branch_tallies(self, busy_store: LoanStore) -> None:
        tallies = {t["branch"]: t for t in busy_store.branch_tallies()}
        northgate = tallies["Northgate"]
        # Northgate: L-1 overdue, L-2 due soon, L-5 returned, 1 waiting hold
        assert northgate["loans_active"] == 2
        assert northgate["overdue"] == 1
        assert northgate["due_soon"] == 1
        assert northgate["holds"] == 1
        westown = tallies["Westown"]
        assert westown["loans_active"] == 2
        assert westown["due_soon"] == 1
        assert westown["holds"] == 1  # the ready hold still counts until picked up

    def test_branch_tallies_exclude_returned(self, fresh_store: LoanStore) -> None:
        loan = fresh_store.record_loan("Soon Gone", "", "Northgate")
        fresh_store.return_loan(loan.id)
        tallies = fresh_store.branch_tallies()
        assert (len(tallies) == 0) or all(t["loans_active"] == 0 for t in tallies)

    def test_status_of_returned_loan_is_returned(self, fresh_store: LoanStore) -> None:
        loan = fresh_store.record_loan("Any Book", "", "Northgate")
        returned = fresh_store.return_loan(loan.id)
        assert loan_status(returned, fresh_store.today()) == "returned"


class TestUnknownIds:
    def test_unknown_loan_id(self, fresh_store: LoanStore) -> None:
        with pytest.raises(LoanError, match="No loan 'L-42'"):
            fresh_store.find_loan("L-42")

    def test_unknown_loan_readably(self, fresh_store: LoanStore) -> None:
        with pytest.raises(LoanError, match="Known loans"):
            fresh_store.find_loan("L-9")
