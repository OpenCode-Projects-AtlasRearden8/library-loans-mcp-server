"""Persistence for the loans tracker: one JSON file, all local.

The store keeps a dict of loans + holds on disk and hands back domain
objects from loans.py. Every change is written atomically (temp file +
rename) so a crash mid-write cannot corrupt the data.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .loans import (
    ACTIVE_HOLD_STATUSES,
    DEFAULT_DUE_SOON_DAYS,
    DEFAULT_LOAN_DAYS,
    Hold,
    Loan,
    LoanError,
    check_hold_transition,
    check_renewal,
    compute_default_due,
    loan_status,
    normalize_title,
    parse_date,
)


def _blank_data() -> dict[str, Any]:
    """Fresh empty store contents (per call, so nothing is shared)."""
    return {
        "loans": [],
        "holds": [],
        "next_loan_id": 1,
        "next_hold_id": 1,
    }

DEFAULT_LOAN_ID_PREFIX = "L-"
DEFAULT_HOLD_ID_PREFIX = "H-"


@dataclass
class LoanStore:
    path: Path

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self._today: Callable[[], date] = date.today
        self._data: dict[str, Any] = {}
        self._load()

    # ---------------------------------------------------------------- time
    def today(self) -> date:
        """Reference date overrideable in tests."""
        return self._today()

    @property
    def next_loan_id(self) -> int:
        return int(self._data.get("next_loan_id", 1))

    @property
    def next_hold_id(self) -> int:
        return int(self._data.get("next_hold_id", 1))

    # ------------------------------------------------------------ loading
    def _load(self) -> None:
        if not self.path.exists():
            self._data = _blank_data()
            self._save()
            return
        self._load_content(self.path.read_text(encoding="utf-8"))

    def _load_content(self, text: str) -> None:
        if not text.strip():
            self._data = _blank_data()
            return
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LoanError(
                f"{self.path} is not valid JSON ({exc.msg} at line {exc.lineno}). "
                "Fix or remove the file - a backup copy can be made before repairs."
            ) from None
        if not isinstance(parsed, dict):
            raise LoanError(f"{self.path} should hold a JSON object of loans and holds.")
        self._data = parsed
        for loan in self.all_loans():
            pass  # from_dict ran during all_loans(); raises on bad records
        for hold in self.all_holds():
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, prefix=self.path.name,
            suffix=".tmp", delete=False,
        ) as handle:
            json.dump(self._data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(handle.name, self.path)

    # ------------------------------------------------------------ lookups
    def all_loans(self) -> list[Loan]:
        return [
            Loan.from_dict(raw)
            for raw in self._data.get("loans", [])
        ]

    def all_holds(self) -> list[Hold]:
        return [
            Hold.from_dict(raw)
            for raw in self._data.get("holds", [])
        ]

    def active_loans(self) -> list[Loan]:
        return [loan for loan in self.all_loans() if loan.returned is None]

    def find_loan(self, loan_id: str) -> Loan:
        for loan in self.all_loans():
            if loan.id == loan_id:
                return loan
        known = ", ".join(loan.id for loan in self.all_loans()) or "(none yet)"
        raise LoanError(
            f"No loan {loan_id!r}. Known loans: {known}."
        )

    def find_hold(self, hold_id: str) -> tuple[Hold, int]:
        for index, raw in enumerate(self._data.get("holds", [])):
            if str(raw.get("id")) == hold_id:
                return Hold.from_dict(raw), index
        known = ", ".join(h.get("id", "?") for h in self._data.get("holds", [])) or "(none yet)"
        raise LoanError(f"No hold {hold_id!r}. Known holds: {known}.")

    # -------------------------------------------------------------- loans
    def record_loan(
        self,
        title: str,
        author: str = "",
        branch: str = "",
        checked_out: str | None = None,
        due: str | None = None,
        loan_days: int = DEFAULT_LOAN_DAYS,
    ) -> Loan:
        """Save a new checkout with its due date and hand it back."""
        if not (title or "").strip():
            raise LoanError("Give the book a title - even a partial one works.")
        if not (branch or "").strip():
            raise LoanError("Which branch is it borrowed from? e.g. 'Northgate'.")
        if due is not None and checked_out is None:
            # allow due-only records: treat checkout as the day before math base
            raise LoanError(
                "If you set a due date, also tell us the checked_out date so the loan has a start."
            )
        checkout_day = self.today() if checked_out is None else parse_date(checked_out)
        due_day = compute_default_due(checkout_day, loan_days) if due is None else parse_date(due)
        if due_day < checkout_day:
            raise LoanError(
                f"The due date {due_day.isoformat()} is before the checkout day "
                f"{checkout_day.isoformat()}. Dates may have been swapped?"
            )
        loan = Loan(
            id=f"{DEFAULT_LOAN_ID_PREFIX}{self.next_loan_id}",
            title=title.strip(),
            author=author.strip(),
            branch=branch.strip(),
            checked_out=checkout_day,
            due=due_day,
        )
        self._data.setdefault("loans", []).append(loan.to_dict())
        self._data["next_loan_id"] = self.next_loan_id + 1
        self._save()
        return loan

    def renew_loan(self, loan_id: str, days: int = DEFAULT_LOAN_DAYS) -> Loan:
        loan = self.find_loan(loan_id)
        new_due = check_renewal(loan, self.today(), self.all_holds(), days)
        for raw in self._data.get("loans", []):
            if str(raw.get("id")) == loan_id:
                raw["due"] = new_due.isoformat()
                raw["renewals"] = loan.renewals + 1
                break
        self._save()
        loan.due = new_due
        loan.renewals += 1
        return loan

    def return_loan(self, loan_id: str, returned_on: str | None = None) -> Loan:
        loan = self.find_loan(loan_id)
        if loan.returned is not None:
            raise LoanError(
                f"{loan.title} was already returned on {loan.returned.isoformat()}."
            )
        day = self.today() if returned_on is None else parse_date(returned_on)
        for raw in self._data.get("loans", []):
            if str(raw.get("id")) == loan_id:
                raw["returned"] = day.isoformat()
                break
        self._save()
        loan.returned = day
        return loan

    # -------------------------------------------------------------- holds
    def place_hold(self, title: str, branch: str) -> Hold:
        if not (title or "").strip():
            raise LoanError("Give the book a title to place a hold on.")
        if not (branch or "").strip():
            raise LoanError("Which branch is it for? e.g. 'Northgate'.")
        folded = normalize_title(title)
        for hold in self.all_holds():
            if (
                hold.status in ACTIVE_HOLD_STATUSES
                and normalize_title(hold.title) == folded
                and hold.branch.strip().casefold() == branch.strip().casefold()
            ):
                raise LoanError(
                    f"There is already a {hold.status!r} hold for {hold.title!r} at "
                    f"{hold.branch} ({hold.id}) - one active hold per title per branch. "
                    "Check `list_holds` before adding another."
                )
        hold = Hold(
            id=f"{DEFAULT_HOLD_ID_PREFIX}{self.next_hold_id}",
            title=title.strip(),
            branch=branch.strip(),
            placed=self.today(),
        )
        self._data.setdefault("holds", []).append(hold.to_dict())
        self._data["next_hold_id"] = self.next_hold_id + 1
        self._save()
        return hold

    def update_hold(self, hold_id: str, new_status: str) -> Hold:
        hold, index = self.find_hold(hold_id)
        check_hold_transition(hold, new_status)
        self._data["holds"][index]["status"] = new_status
        self._save()
        hold.status = new_status
        return hold

    def cancel_hold(self, hold_id: str) -> Hold:
        return self.update_hold(hold_id, "cancelled")

    # ------------------------------------------------------------ reports
    def due_soon(self, days: int = DEFAULT_DUE_SOON_DAYS) -> list[tuple[Loan, str]]:
        """Active loans due within `days` of today (or already overdue? no)."""
        if days < 1:
            raise LoanError("Give a window of at least 1 day.")
        result = []
        for loan in self.active_loans():
            state = loan_status(loan, self.today(), days)
            if state == "due_soon":
                result.append((loan, state))
        return result

    def overdue_loans(self) -> list[Loan]:
        return [
            loan
            for loan in self.active_loans()
            if loan_status(loan, self.today()) == "overdue"
        ]

    def branch_tallies(self) -> list[dict[str, int]]:
        """Per branch: active loans, overdue, due soon, and ready/waiting holds."""
        today = self.today()
        counts: dict[str, dict[str, int]] = {}
        for loan in self.all_loans():
            branch = loan.branch or "(unknown branch)"
            bucket = counts.setdefault(
                branch, {"loans_active": 0, "overdue": 0, "due_soon": 0, "holds": 0}
            )
            state = loan_status(loan, today)
            if state != "returned":
                bucket["loans_active"] += 1
                if state in ("overdue", "due_soon"):
                    bucket[state] += 1
        for hold in self.all_holds():
            if hold.status in ACTIVE_HOLD_STATUSES:
                branch = hold.branch or "(unknown branch)"
                bucket = counts.setdefault(
                    branch, {"loans_active": 0, "overdue": 0, "due_soon": 0, "holds": 0}
                )
                bucket["holds"] += 1
        return [dict(branch=branch, **bucket) for branch, bucket in sorted(counts.items())]
