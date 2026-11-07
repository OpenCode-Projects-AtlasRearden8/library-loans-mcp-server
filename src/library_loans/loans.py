"""Pure domain logic for library loans: dates, renewals, and holds.

Everything here is plain data plus date math, so it is easy to test with a
frozen "today". Persistence lives in store.py, MCP wiring in server.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

MAX_RENEWALS = 2
DEFAULT_LOAN_DAYS = 21
DEFAULT_DUE_SOON_DAYS = 7

# Loan states derived from the due date (computed, never stored).
LOAN_STATES = ("returned", "overdue", "due_soon", "on_time")

HOLD_STATUSES = ("waiting", "ready", "picked_up", "cancelled")
ACTIVE_HOLD_STATUSES = ("waiting", "ready")

HOLD_TRANSITIONS = {
    "waiting": ("ready", "cancelled"),
    "ready": ("picked_up", "cancelled"),
    "picked_up": (),
    "cancelled": (),
}


class LoanError(Exception):
    """Friendly, actionable error for a loan/hold problem."""


def parse_date(raw: str) -> date:
    """Parse an ISO date (YYYY-MM-DD) and raise a readable error otherwise."""
    if not isinstance(raw, str):
        raise LoanError("Dates should be text in YYYY-MM-DD form, like 2026-11-15.")
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise LoanError(
            f"{raw!r} is not a date we understand. Use YYYY-MM-DD, like 2026-11-15."
        ) from None


def normalize_title(raw: str) -> str:
    """Fold titles for comparing (case and extra spaces ignored)."""
    return " ".join(raw.split()).casefold()


@dataclass
class Loan:
    id: str
    title: str
    author: str
    branch: str
    checked_out: date
    due: date
    renewals: int = 0
    returned: date | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
            "branch": self.branch,
            "checked_out": self.checked_out.isoformat(),
            "due": self.due.isoformat(),
            "renewals": self.renewals,
            "returned": self.returned.isoformat() if self.returned else None,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Loan:
        try:
            return cls(
                id=str(raw["id"]),
                title=str(raw["title"]),
                author=str(raw.get("author", "")),
                branch=str(raw.get("branch", "")),
                checked_out=parse_date(raw["checked_out"]),
                due=parse_date(raw["due"]),
                renewals=int(raw.get("renewals", 0)),
                returned=parse_date(raw["returned"]) if raw.get("returned") else None,
            )
        except KeyError as exc:
            raise LoanError(f"Loan record is missing {exc.args[0]!r}.") from None


@dataclass
class Hold:
    id: str
    title: str
    branch: str
    placed: date
    status: str = "waiting"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "branch": self.branch,
            "placed": self.placed.isoformat(),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Hold:
        try:
            status = str(raw.get("status", "waiting"))
            if status not in HOLD_STATUSES:
                raise LoanError(f"Unknown hold status {status!r}.")
            return cls(
                id=str(raw["id"]),
                title=str(raw["title"]),
                branch=str(raw.get("branch", "")),
                placed=parse_date(raw["placed"]),
                status=status,
            )
        except KeyError as exc:
            raise LoanError(f"Hold record is missing {exc.args[0]!r}.") from None


def compute_default_due(checked_out: date, loan_days: int) -> date:
    """Standard loan length: checkout day plus loan_days."""
    if loan_days < 1:
        raise LoanError("Loan length must be at least 1 day.")
    return checked_out + timedelta(days=loan_days)


def loan_status(
    loan: Loan, today: date, due_soon_days: int = DEFAULT_DUE_SOON_DAYS
) -> str:
    """Classify a loan against 'today': returned/overdue/due_soon/on_time."""
    if loan.returned is not None:
        return "returned"
    if loan.due < today:
        return "overdue"
    if loan.due <= today + timedelta(days=due_soon_days):
        return "due_soon"
    return "on_time"


def check_renewal(
    loan: Loan, today: date, holds: list[Hold], days: int = DEFAULT_LOAN_DAYS
) -> date:
    """Validate a renewal and return the new due date, or raise LoanError.

    A renewal pushes the due date out from the *current due date*, so time
    already borrowed is preserved. Blocked when the loan is overdue, out of
    renewals, or an active hold (waiting/ready) sits on the same title.
    """
    if days < 1:
        raise LoanError("A renewal must add at least 1 day.")
    if loan.returned is not None:
        raise LoanError(
            f"{loan.title} was already returned on {loan.returned.isoformat()}, "
            "so there is nothing to renew. Check it out again if needed."
        )
    if loan.due < today:
        raise LoanError(
            f"{loan.title} is overdue (was due {loan.due.isoformat()}). "
            "Renewals are not allowed on overdue items - return it or visit the branch."
        )
    if loan.renewals >= MAX_RENEWALS:
        raise LoanError(
            f"{loan.title} is out of renewals ({loan.renewals}/{MAX_RENEWALS} used). "
            "Return it by its due date and check it out again later."
        )
    folded = normalize_title(loan.title)
    blockers = [
        h
        for h in holds
        if h.status in ACTIVE_HOLD_STATUSES and normalize_title(h.title) == folded
    ]
    if blockers:
        holder = blockers[0]
        raise LoanError(
            f"Cannot renew {loan.title} - {holder.branch} has a hold with status "
            f"{holder.status!r} on that title and someone is waiting for this copy."
        )
    return loan.due + timedelta(days=days)


def check_hold_transition(hold: Hold, new_status: str) -> str:
    """Validate a status change for a hold and return the accepted status."""
    if new_status not in HOLD_STATUSES:
        wanted = ", ".join(HOLD_STATUSES)
        raise LoanError(
            f"{new_status!r} is not a hold status. Use one of: {wanted}."
        )
    if hold.status == new_status:
        raise LoanError(f"Hold {hold.id} is already {new_status!r}, nothing to change.")
    allowed = HOLD_TRANSITIONS[hold.status]
    if new_status not in allowed:
        if not allowed:
            raise LoanError(
                f"Hold {hold.id} is {hold.status!r}, which is final - it cannot move "
                f"to {new_status!r}. Place a new hold if you want it again."
            )
        raise LoanError(
            f"Hold {hold.id} cannot go from {hold.status!r} to {new_status!r}. "
            f"Allowed next statuses: {', '.join(allowed)}."
        )
    return new_status
