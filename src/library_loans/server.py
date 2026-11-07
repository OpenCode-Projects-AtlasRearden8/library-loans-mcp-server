"""MCP server exposing the library loans tracker over stdio.

Works with `mcp` 1.x (FastMCP) and 2.x (MCPServer). Run with:

    python -m library_loans.server

Every tool result is plain, readable text an AI agent can act on.
All data stays on disk at home - no cloud, no accounts, no uploads.
"""

from __future__ import annotations

import os
from pathlib import Path

from .loans import (
    DEFAULT_DUE_SOON_DAYS,
    DEFAULT_LOAN_DAYS,
    HOLD_STATUSES,
    MAX_RENEWALS,
    LoanError,
    loan_status,
)
from .store import LoanStore

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _MCP  # type: ignore

    _MCP_VERSION = "1.x"
except ImportError:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as _MCP  # type: ignore

    _MCP_VERSION = "2.x"


def _default_path() -> Path:
    raw = os.environ.get("LIBRARY_LOANS_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent.parent.parent / "data" / "loans.json"


def _date_text(day) -> str:
    return day.isoformat() if day else "-"


def build_server(store: LoanStore | None = None):
    """Create the MCP server bound to a store (default path from env)."""
    store = store or LoanStore(_default_path())
    server = _MCP(
        "library-loans",
        title="Library Loans Tracker",
        description=(
            "A local tracker for borrowed library books: record loans, holds, "
            "and renewals; check what is due soon, overdue, and how counts look "
            "per branch. All data stays on disk at home."
        ),
    )

    def loan_line(loan, state: str) -> str:
        mark = {
            "overdue": "OVERDUE",
            "due_soon": "due soon",
            "on_time": "on time",
            "returned": "returned",
        }[state]
        author = f" by {loan.author}" if loan.author else ""
        return (
            f"{loan.id}  {loan.title}{author}  branch={loan.branch}  "
            f"checked_out={loan.checked_out.isoformat()}  "
            f"due={loan.due.isoformat()}  renewals={loan.renewals}/{MAX_RENEWALS}  "
            f"[{mark}]"
        )

    @server.tool()
    def record_loan(
        title: str,
        branch: str,
        author: str = "",
        checked_out: str | None = None,
        due: str | None = None,
        loan_days: int = DEFAULT_LOAN_DAYS,
    ) -> str:
        """Record a checked-out book. Dates use YYYY-MM-DD; checked_out
        defaults to today and due defaults to checked_out + loan_days (21)."""
        try:
            loan = store.record_loan(
                title, author, branch, checked_out, due, loan_days
            )
        except LoanError as exc:
            return f"Could not record the loan: {exc}"
        return (
            f"Recorded {loan.id}: {loan.title} from {loan.branch}, "
            f"checked out {loan.checked_out.isoformat()}, "
            f"due {loan.due.isoformat()}."
        )

    @server.tool()
    def renew_loan(loan_id: str, days: int = DEFAULT_LOAN_DAYS) -> str:
        """Extend a loan by `days` from its current due date. Blocked if the
        loan is overdue, out of renewals (2), or an active hold has that title."""
        try:
            loan = store.renew_loan(loan_id, days)
        except LoanError as exc:
            return f"Could not renew: {exc}"
        return (
            f"Renewed {loan.id} ({loan.title}): due date moved to "
            f"{loan.due.isoformat()}. Renewals used {loan.renewals}/{MAX_RENEWALS}."
        )

    @server.tool()
    def return_loan(loan_id: str, returned_on: str | None = None) -> str:
        """Mark a loan returned (default today, or YYYY-MM-DD)."""
        try:
            loan = store.return_loan(loan_id, returned_on)
        except LoanError as exc:
            return f"Could not mark the return: {exc}"
        extra = ""
        if loan_status(loan, loan.returned) == "overdue":
            extra = " It went back after its due date."
        return (
            f"Marked {loan.id} ({loan.title}) returned on "
            f"{loan.returned.isoformat()}.{extra}"
        )

    @server.tool()
    def list_loans(active_only: bool = True) -> str:
        """List loans, newest last. Default shows only active (not returned)."""
        loans = store.active_loans() if active_only else store.all_loans()
        if not loans:
            return "No loans on file yet - use `record_loan` to add one."
        today = store.today()
        lines = [
            loan_line(loan, loan_status(loan, today)) for loan in loans
        ]
        header = "Active loans:" if active_only else "All loans (returned included):"
        return header + "\n" + "\n".join(lines)

    @server.tool()
    def due_soon(days: int = DEFAULT_DUE_SOON_DAYS) -> str:
        """Active loans due within `days` of today (default 7)."""
        try:
            soon = store.due_soon(days)
        except LoanError as exc:
            return f"Could not list due-soon items: {exc}"
        if not soon:
            return (
                f"Nothing due in the next {days} day(s) - all clear for the moment."
            )
        lines = "\n".join(
            loan_line(loan, state) for loan, state in soon
        )
        return f"Due within the next {days} day(s) - plan a branch stop:" + "\n" + lines

    @server.tool()
    def list_overdue() -> str:
        """Loans past their due date, most-urgent first."""
        overdue = store.overdue_loans()
        if not overdue:
            return "Nothing overdue - nice work keeping on top of it."
        overdue.sort(key=lambda loan: loan.due)
        lines = "\n".join(loan_line(loan, "overdue") for loan in overdue)
        return f"{len(overdue)} loan(s) overdue - renew or return soon:" + "\n" + lines

    @server.tool()
    def branch_tallies() -> str:
        """Per-branch counts: active loans, overdue, due soon, and open holds."""
        tallies = store.branch_tallies()
        total_active = sum(t["loans_active"] for t in tallies)
        total_due = sum(t["due_soon"] for t in tallies)
        total_over = sum(t["overdue"] for t in tallies)
        total_holds = sum(t["holds"] for t in tallies)
        rows = "\n".join(
            f"{t['branch']}: active={t['loans_active']}  due_soon={t['due_soon']}  "
            f"overdue={t['overdue']}  open_holds={t['holds']}"
            for t in tallies
        )
        return (
            "Branch tallies (all local branches):\n"
            + rows
            + (
                f"\nTotals: active={total_active}  due_soon={total_due}  "
                f"overdue={total_over}  open_holds={total_holds}"
            )
        )

    @server.tool()
    def place_hold(title: str, branch: str) -> str:
        """Place a hold (waiting status) on a title at a branch. One active
        hold per title per branch."""
        try:
            hold = store.place_hold(title, branch)
        except LoanError as exc:
            return f"Could not place the hold: {exc}"
        return (
            f"Placed hold {hold.id}: {hold.title} at {hold.branch}, "
            f"status waiting since {hold.placed.isoformat()}. "
            "Update it to 'ready' when the branch lets you know."
        )

    @server.tool()
    def update_hold(hold_id: str, status: str) -> str:
        """Move a hold along: waiting -> ready -> picked_up. Cancel from
        waiting or ready. Use YYYY-MM-DD-worthy caution; statuses cannot undo."""
        try:
            hold = store.update_hold(hold_id, status)
        except LoanError as exc:
            return f"Could not update the hold: {exc}"
        return f"Hold {hold.id} ({hold.title} at {hold.branch}) is now {hold.status!r}."

    @server.tool()
    def cancel_hold(hold_id: str) -> str:
        """Cancel a hold that is waiting or ready (final state)."""
        try:
            hold = store.cancel_hold(hold_id)
        except LoanError as exc:
            return f"Could not cancel the hold: {exc}"
        return f"Hold {hold.id} ({hold.title} at {hold.branch}) is now cancelled."

    @server.tool()
    def list_holds(status: str | None = None) -> str:
        """List holds (all, or filtered: waiting, ready, picked_up, cancelled)."""
        if status is not None and status not in HOLD_STATUSES:
            wanted = ", ".join(HOLD_STATUSES)
            return (
                f"Could not list holds: {status!r} is not a status. Use one of: {wanted}."
            )
        holds = [
            hold
            for hold in store.all_holds()
            if status is None or hold.status == status
        ]
        if not holds:
            filter_note = f" with status {status!r}" if status else ""
            return f"No holds{filter_note} - use `place_hold` to add one."
        lines = [
            f"{h.id}  {h.title}  branch={h.branch}  placed={h.placed.isoformat()}  "
            f"status={h.status}"
            for h in holds
        ]
        return "Holds on file:" + "\n" + "\n".join(lines)

    return server


def main() -> None:
    import sys

    server = build_server()
    print(
        f"library-loans MCP server ({_MCP_VERSION}) starting on stdio...",
        file=sys.stderr,
    )
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
