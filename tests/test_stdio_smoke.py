"""Stdio smoke test: boot the real server as a subprocess and talk MCP to it.

Uses the official `mcp` client against a throwaway data file. Skipped
cleanly if the client pieces are unavailable in the installed SDK version.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp.client")

from mcp.client import Client, stdio


@pytest.fixture
def params(tmp_path: Path) -> tuple[stdio.StdioServerParameters, Path]:
    log_path = tmp_path / "smoke.json"
    params = stdio.StdioServerParameters(
        command=sys.executable,
        args=["-m", "library_loans.server"],
        env={
            **os.environ,
            "LIBRARY_LOANS_PATH": str(log_path),
            "PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src"),
        },
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    return params, log_path


def test_stdio_roundtrip(params) -> None:
    run_params, log_path = params

    async def main() -> str:
        async with Client(run_params) as client:
            tools_result = await client.list_tools()
            tools = (
                tools_result.tools if hasattr(tools_result, "tools") else tools_result
            )
            names = {
                t["name"] if isinstance(t, dict) else t.name for t in tools
            }
            assert {
                "record_loan",
                "renew_loan",
                "due_soon",
                "list_overdue",
                "branch_tallies",
                "place_hold",
            } <= names
            first = await client.call_tool(
                "record_loan",
                {"title": "Smoke Test Book", "branch": "Northgate", "author": ""},
            )
            await client.call_tool(
                "place_hold", {"title": "Smoke Test Sequel", "branch": "Northgate"}
            )
            tallies = await client.call_tool("branch_tallies", {})
        return first.content[0].text + "\n" + tallies.content[0].text  # type: ignore[index,union-attr]

    text = asyncio.run(main())
    assert "Recorded L-1" in text
    assert "Northgate" in text
    saved = log_path.read_text(encoding="utf-8").splitlines()
    assert len(saved) >= 2  # pretty-printed JSON of the store
