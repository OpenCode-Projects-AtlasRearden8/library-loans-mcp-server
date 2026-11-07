"""Tests for hold placement, transitions, and their edge cases."""

from __future__ import annotations

from datetime import date

import pytest

from library_loans.loans import HOLD_STATUSES, HOLD_TRANSITIONS, LoanError
from library_loans.store import LoanStore

TODAY = date(2026, 11, 7)


class TestPlaceHold:
    def test_places_waiting_hold(self, fresh_store: LoanStore) -> None:
        hold = fresh_store.place_hold("The Long Ship", "Northgate")
        assert hold.status == "waiting"
        assert hold.id == "H-1"
        assert hold.placed.isoformat() == "2026-11-07"

    def test_ids_increase(self, fresh_store: LoanStore) -> None:
        fresh_store.place_hold("First", "Northgate")
        hold2 = fresh_store.place_hold("Second", "Westown")
        assert hold2.id == "H-2"

    def test_duplicate_active_hold_same_branch_rejected(self, fresh_store: LoanStore) -> None:
        fresh_store.place_hold("The Long Ship", "Northgate")
        with pytest.raises(LoanError, match="already"):
            fresh_store.place_hold("The Long Ship", "Northgate")

    def test_duplicate_matching_ignores_case_and_spacing(self, fresh_store: LoanStore) -> None:
        fresh_store.place_hold("The Long Ship", "Northgate")
        with pytest.raises(LoanError):
            fresh_store.place_hold("  the  LONG ship ", "northgate")

    def test_same_title_other_branch_is_ok(self, fresh_store: LoanStore) -> None:
        fresh_store.place_hold("The Long Ship", "Northgate")
        hold = fresh_store.place_hold("The Long Ship", "Westown")
        assert hold.status == "waiting"

    def test_new_hold_allowed_after_cancel(self, fresh_store: LoanStore) -> None:
        hold = fresh_store.place_hold("The Long Ship", "Northgate")
        fresh_store.cancel_hold(hold.id)
        again = fresh_store.place_hold("The Long Ship", "Northgate")
        assert again.status == "waiting"
        assert again.id != hold.id

    def test_new_hold_allowed_after_pickup(self, fresh_store: LoanStore) -> None:
        hold = fresh_store.place_hold("The Long Ship", "Northgate")
        fresh_store.update_hold(hold.id, "ready")
        fresh_store.update_hold(hold.id, "picked_up")
        again = fresh_store.place_hold("The Long Ship", "Northgate")
        assert again.status == "waiting"

    def test_blank_title_or_branch_rejected(self, fresh_store: LoanStore) -> None:
        with pytest.raises(LoanError, match="title"):
            fresh_store.place_hold("   ", "Northgate")
        with pytest.raises(LoanError, match="branch"):
            fresh_store.place_hold("The Long Ship", "")

    def test_hold_blocks_renewal_while_waiting(self, busy_store: LoanStore) -> None:
        loan = busy_store.record_loan("The Kenya Letters", "A. Nairobian", "Westown",
                                      checked_out="2026-10-01", due="2026-11-12")
        busy_store.place_hold("the kenya letters", "Northgate")
        with pytest.raises(LoanError, match="hold"):
            busy_store.renew_loan(loan.id)

    def test_hold_blocks_renewal_while_ready(self, fresh_store: LoanStore) -> None:
        loan = fresh_store.record_loan("Salt Roads", "", "Northgate")
        hold = fresh_store.place_hold("Salt Roads", "Northgate")
        fresh_store.update_hold(hold.id, "ready")
        with pytest.raises(LoanError, match="waiting for this copy"):
            fresh_store.renew_loan(loan.id)

    def test_cancelled_hold_does_not_block_renewal(self, fresh_store: LoanStore) -> None:
        loan = fresh_store.record_loan("Salt Roads", "", "Northgate")
        hold = fresh_store.place_hold("Salt Roads", "Northgate")
        fresh_store.cancel_hold(hold.id)
        renewed = fresh_store.renew_loan(loan.id)
        assert renewed.renewals == 1

    def test_picked_up_hold_does_not_block_renewal(self, fresh_store: LoanStore) -> None:
        loan = fresh_store.record_loan("Salt Roads", "", "Northgate")
        hold = fresh_store.place_hold("Salt Roads", "Northgate")
        fresh_store.update_hold(hold.id, "ready")
        fresh_store.update_hold(hold.id, "picked_up")
        renewed = fresh_store.renew_loan(loan.id)
        assert renewed.renewals == 1

    def test_hold_on_other_title_does_not_block(self, fresh_store: LoanStore) -> None:
        loan = fresh_store.record_loan("Salt Roads", "", "Northgate")
        fresh_store.place_hold("Different Book", "Northgate")
        renewed = fresh_store.renew_loan(loan.id)
        assert renewed.renewals == 1


class TestHoldTransitions:
    def test_waiting_to_ready(self, fresh_store: LoanStore) -> None:
        hold = fresh_store.place_hold("Road Work", "Northgate")
        assert fresh_store.update_hold(hold.id, "ready").status == "ready"

    def test_ready_to_picked_up(self, fresh_store: LoanStore) -> None:
        hold = fresh_store.place_hold("Road Work", "Northgate")
        fresh_store.update_hold(hold.id, "ready")
        assert fresh_store.update_hold(hold.id, "picked_up").status == "picked_up"

    def test_waiting_can_be_cancelled(self, fresh_store: LoanStore) -> None:
        hold = fresh_store.place_hold("Road Work", "Northgate")
        assert fresh_store.cancel_hold(hold.id).status == "cancelled"

    def test_ready_can_be_cancelled(self, fresh_store: LoanStore) -> None:
        hold = fresh_store.place_hold("Road Work", "Northgate")
        fresh_store.update_hold(hold.id, "ready")
        assert fresh_store.cancel_hold(hold.id).status == "cancelled"

    def test_waiting_cannot_jump_to_picked_up(self, fresh_store: LoanStore) -> None:
        hold = fresh_store.place_hold("Road Work", "Northgate")
        with pytest.raises(LoanError, match="cannot go"):
            fresh_store.update_hold(hold.id, "picked_up")

    def test_terminal_states_avoid_new_moves(self, fresh_store: LoanStore) -> None:
        hold = fresh_store.place_hold("Road Work", "Northgate")
        fresh_store.cancel_hold(hold.id)
        for status in ("ready", "picked_up", "waiting"):
            with pytest.raises(LoanError, match="is final"):
                fresh_store.update_hold(hold.id, status)
        picked = fresh_store.place_hold("Second Try", "Northgate")
        fresh_store.update_hold(picked.id, "ready")
        fresh_store.update_hold(picked.id, "picked_up")
        with pytest.raises(LoanError, match="is final"):
            fresh_store.update_hold(picked.id, "cancelled")

    def test_unknown_status_rejected(self, fresh_store: LoanStore) -> None:
        hold = fresh_store.place_hold("Road Work", "Northgate")
        with pytest.raises(LoanError, match="not a hold status"):
            fresh_store.update_hold(hold.id, "expired")

    def test_same_status_is_no_op_error(self, fresh_store: LoanStore) -> None:
        hold = fresh_store.place_hold("Road Work", "Northgate")
        with pytest.raises(LoanError, match="already"):
            fresh_store.update_hold(hold.id, "waiting")

    def test_transition_table_covers_all_statuses(self) -> None:
        assert set(HOLD_STATUSES) == {"waiting", "ready", "picked_up", "cancelled"}
        for nexts in HOLD_TRANSITIONS.values():
            assert all(s in HOLD_STATUSES for s in nexts)

    def test_transition_validator_accepts_then_returns_status(self) -> None:
        from library_loans.loans import Hold, check_hold_transition

        hold = Hold(id="H-1", title="T", branch="B", placed=TODAY)
        assert check_hold_transition(hold, "ready") == "ready"

    def test_cancel_unknown_hold_id(self, fresh_store: LoanStore) -> None:
        with pytest.raises(LoanError, match="No hold"):
            fresh_store.cancel_hold("H-99")


class TestHoldDefaults:
    def test_bad_status_in_file_rejected(self, tmp_path) -> None:
        import json

        path = tmp_path / "loans.json"
        path.write_text(json.dumps({"holds": [{
            "id": "H-1", "title": "X", "branch": "Y", "placed": "2026-11-01",
            "status": "teleported",
        }]}), encoding="utf-8")
        with pytest.raises(LoanError):
            LoanStore(path)
