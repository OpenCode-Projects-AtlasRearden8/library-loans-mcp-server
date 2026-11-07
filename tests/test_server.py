"""End-to-end tests for the MCP server: tool listing, calls, readable text."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from library_loans.server import build_server
from library_loans.store import LoanStore


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def tool_text(result: Any) -> str:
    assert result.is_error is False, result
    return result.content[0].text  # type: ignore[union-attr, index]


class TestToolListing:
    def test_list_tools(self, fresh_store: LoanStore) -> None:
        names = {t.name for t in run(build_server(fresh_store).list_tools())}
        assert {
            "record_loan",
            "renew_loan",
            "return_loan",
            "list_loans",
            "due_soon",
            "list_overdue",
            "branch_tallies",
            "place_hold",
            "update_hold",
            "cancel_hold",
            "list_holds",
        } == names


class TestRecordLoanTool:
    def test_record_and_read_back(self, fresh_store: LoanStore) -> None:
        server = build_server(fresh_store)
        text = tool_text(run(server.call_tool(
            "record_loan",
            {"title": "The Hidden Life of Trees", "author": "Peter Wohlleben",
             "branch": "Northgate"},
        )))
        assert "Recorded L-1" in text
        assert "due 2026-11-28" in text  # today (frozen 2026-11-07) + 21 days

    def test_bad_dates_reported_gracefully(self, fresh_store: LoanStore) -> None:
        text = tool_text(run(build_server(fresh_store).call_tool(
            "record_loan",
            {"title": "Oops", "branch": "Northgate", "checked_out": "Nov 5"},
        )))
        assert "Could not record the loan" in text

    def test_missing_branch_hint(self, fresh_store: LoanStore) -> None:
        text = tool_text(run(build_server(fresh_store).call_tool(
            "record_loan", {"title": "Oops", "branch": "   "},
        )))
        assert "Which branch" in text


class TestRenewTool:
    def test_renew_success(self, fresh_store: LoanStore) -> None:
        server = build_server(fresh_store)
        tool_text(run(server.call_tool(
            "record_loan",
            {"title": "Renew Me", "branch": "Northgate",
             "checked_out": "2026-10-21", "due": "2026-11-12"},
        )))
        text = tool_text(run(server.call_tool("renew_loan", {"loan_id": "L-1"})))
        assert "due date moved to 2026-12-03" in text

    def test_overdue_renew_refused(self, fresh_store: LoanStore) -> None:
        server = build_server(fresh_store)
        tool_text(run(server.call_tool(
            "record_loan",
            {"title": "Too Late", "branch": "Northgate",
             "checked_out": "2026-10-01", "due": "2026-10-22"},
        )))
        text = tool_text(run(server.call_tool("renew_loan", {"loan_id": "L-1"})))
        assert "Cannot renew" not in text
        assert "Could not renew: 'The lending branch'" not in text
        assert "Could not renew" in text and "overdue" in text

    def test_hold_blocks_renew_readably(self, fresh_store: LoanStore) -> None:
        server = build_server(fresh_store)
        tool_text(run(server.call_tool(
            "record_loan",
            {"title": "Busy Book", "branch": "Northgate"},
        )))
        tool_text(run(server.call_tool(
            "place_hold", {"title": "busy book", "branch": "Westown"},
        )))
        text = tool_text(run(server.call_tool("renew_loan", {"loan_id": "L-1"})))
        assert "someone is waiting for this copy" in text


class TestDueSoonAndOverdue:
    def test_due_soon_empty(self, fresh_store: LoanStore) -> None:
        text = tool_text(run(build_server(fresh_store).call_tool("due_soon", {})))
        assert "Nothing due" in text

    def test_due_soon_lists(self, busy_store: LoanStore) -> None:
        text = tool_text(run(build_server(busy_store).call_tool("due_soon", {})))
        assert "Project Hail Mary" in text
        assert "[due soon]" in text

    def test_overdue_empty(self, fresh_store: LoanStore) -> None:
        text = tool_text(run(build_server(fresh_store).call_tool("list_overdue", {})))
        assert "Nothing overdue" in text

    def test_overdue_lists(self, busy_store: LoanStore) -> None:
        text = tool_text(run(build_server(busy_store).call_tool("list_overdue", {})))
        assert "OVERDUE" in text
        assert "The Hidden Life of Trees" in text

    def test_branch_tallies_text(self, busy_store: LoanStore) -> None:
        text = tool_text(run(build_server(busy_store).call_tool("branch_tallies", {})))
        assert "Northgate" in text
        assert "open_holds=2" in text  # waiting + ready across branches


class TestHoldsTools:
    def test_place_list_update_cancel(self, fresh_store: LoanStore) -> None:
        server = build_server(fresh_store)
        text = tool_text(run(server.call_tool(
            "place_hold", {"title": "Hold Me", "branch": "Northgate"},
        )))
        assert "Placed hold H-1" in text
        text = tool_text(run(server.call_tool("list_holds", {})))
        assert "status=waiting" in text
        text = tool_text(run(server.call_tool(
            "update_hold", {"hold_id": "H-1", "status": "ready"},
        )))
        assert "is now 'ready'" in text
        text = tool_text(run(server.call_tool("cancel_hold", {"hold_id": "H-1"})))
        assert "cancelled" in text

    def test_duplicate_hold_message(self, fresh_store: LoanStore) -> None:
        server = build_server(fresh_store)
        tool_text(run(server.call_tool(
            "place_hold", {"title": "Dup", "branch": "Northgate"},
        )))
        text = tool_text(run(server.call_tool(
            "place_hold", {"title": "Dup", "branch": "Northgate"},
        )))
        assert "Could not place the hold" in text
        assert "one active hold per title per branch" in text

    def test_update_bad_transition(self, fresh_store: LoanStore) -> None:
        server = build_server(fresh_store)
        tool_text(run(server.call_tool(
            "place_hold", {"title": "Jump", "branch": "Northgate"},
        )))
        text = tool_text(run(server.call_tool(
            "update_hold", {"hold_id": "H-1", "status": "picked_up"},
        )))
        assert "Could not update the hold" in text
        assert "Allowed next statuses" in text

    def test_list_holds_filter(self, fresh_store: LoanStore) -> None:
        server = build_server(fresh_store)
        tool_text(run(server.call_tool(
            "place_hold", {"title": "Filtered", "branch": "Northgate"},
        )))
        text = tool_text(run(server.call_tool(
            "list_holds", {"status": "ready"},
        )))
        assert "No holds with status 'ready'" in text

    def test_list_holds_bad_filter(self, fresh_store: LoanStore) -> None:
        text = tool_text(run(build_server(fresh_store).call_tool(
            "list_holds", {"status": "teleported"},
        )))
        assert "not a status" in text


class TestReturnTool:
    def test_return_marks_loan(self, fresh_store: LoanStore) -> None:
        server = build_server(fresh_store)
        tool_text(run(server.call_tool(
            "record_loan", {"title": "Back Early", "branch": "Northgate"},
        )))
        text = tool_text(run(server.call_tool("return_loan", {"loan_id": "L-1"})))
        assert "returned on 2026-11-07" in text
        text = tool_text(run(server.call_tool("list_loans", {})))
        assert "No loans on file" in text

    def test_return_twice_refused(self, fresh_store: LoanStore) -> None:
        server = build_server(fresh_store)
        tool_text(run(server.call_tool(
            "record_loan", {"title": "Once Only", "branch": "Northgate"},
        )))
        tool_text(run(server.call_tool("return_loan", {"loan_id": "L-1"})))
        text = tool_text(run(server.call_tool("return_loan", {"loan_id": "L-1"})))
        assert "Could not mark the return" in text


class TestEnvPath:
    def test_env_var_overrides(self, tmp_path, monkeypatch) -> None:
        path = tmp_path / "env.json"
        monkeypatch.setenv("LIBRARY_LOANS_PATH", str(path))
        srv = build_server()
        assert srv is not None
        tool_text(run(srv.call_tool(
            "record_loan", {"title": "Env Book", "branch": "Northgate"},
        )))
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["loans"][0]["title"] == "Env Book"
