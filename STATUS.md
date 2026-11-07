# STATUS.md — library-loans-mcp-server

Last updated: 2026-11-07

## What was built

A small, local-first Python MCP server (`stdio` transport) that tracks books
borrowed from public library branches. Goal: an AI agent can record loans,
holds, and renewals and answer "what's due soon / overdue / per-branch" in
plain, readable text.

**Package structure**

- `src/library_loans/loans.py` — pure domain logic: date parsing, due-date
  math, loan status classification (overdue / due soon / on time / returned),
  renewal rules, hold state machine. No I/O.
- `src/library_loans/store.py` — persistence: one JSON file, atomic writes
  (temp file + rename), id counters, queries (`due_soon`, overdues,
  per-branch tallies).
- `src/library_loans/server.py` — MCP server (works with `mcp` 1.x FastMCP
  and 2.x MCPServer), 11 tools, friendly text results.
- `data/loans.json` — blank starter data file (path override via
  `LIBRARY_LOANS_PATH` env var).
- `tests/` — 86 tests: due-date logic, hold edge cases, persistence, MCP
  tool results, and a subprocess stdio smoke test.

**House rules encoded in the tools**

- Renewals extend from the current due date (not today), max 2 renewals,
  never while overdue.
- An active hold (waiting/ready) on the same title blocks renewal; cancelled
  and picked-up holds don't.
- Hold transitions: waiting → ready → picked_up; cancel from waiting/ready;
  picked_up and cancelled are final.
- One active hold per title per branch.

**Loan tool list**: `record_loan`, `renew_loan`, `return_loan`, `list_loans`,
`due_soon`, `list_overdue`, `branch_tallies`, `place_hold`, `update_hold`,
`cancel_hold`, `list_holds`.

Distinct from peers: reading-room-mcp-server (notes/content) and
dates-to-remember-mcp-server (general dates) — this one only tracks the
borrowed-copy lifecycle.

## How to run it

```bash
pip install -e .            # into your env (or venv)
export LIBRARY_LOANS_PATH="$HOME/library-loans/loans.json"   # optional
python3 -m library_loans.server          # stdio MCP server
# or the installed console script: library-loans-server
```

Point an MCP client (opencode, Claude Desktop, etc.) at it:

```json
{
  "mcpServers": {
    "library-loans": {
      "command": "python3",
      "args": ["-m", "library_loans.server"],
      "env": { "LIBRARY_LOANS_PATH": "/home/you/library-loans/loans.json" }
    }
  }
}
```

## Verification results

- `ruff check src tests` — clean (0 errors).
- `pytest tests/ -q` — **86 passed** in ~1.5s. Includes:
  - due-date logic: defaults (+21 days), custom windows, overdue vs due-today
    boundary ("due today" → due soon, not overdue), renewal extending from
    the due date, cap of 2 renewals, renew-after-return refusals.
  - hold edge cases: duplicate active holds (case/whitespace folded),
    re-placement after cancellation or pickup, invalid transitions
    (waiting→picked_up, out of terminal states), unknown statuses/ids,
    holds blocking renewals while active but not when resolved.
  - persistence: fresh-file bootstrap, id counters, reload round-trip,
    corrupt JSON reported readably, missing fields rejected.
  - MCP end-to-end: every tool called through `build_server(...).call_tool`
    with an agent-readable text result; stdio subprocess smoke test via the
    official `mcp` client (initialize → list_tools → call_tool).
- Manual stdio handshake replay (raw JSON-RPC lines): server initializes,
  lists tools, records a loan, and persists it to disk.

## Known gaps / ideas

- Dates are local-date strings (no timezone handling); branches with
  far-away timezones are unlikely to matter here.
- No "pick up by" expiry on ready holds (library-issued hold windows not
  modeled); statuses are manual agent-side truth.
- One per-title hold match uses title text folding, not real item
  barcodes/ISBNs — text collisions are possible but harmless at personal
  scale.
- No multi-user concept, no overdue-fee logic, no notion of separate card
  numbers per branch.
- `list_loans` returns text, not structured JSON — good for agents, but a
  future `--format json` could help integrations.
- No CI workflow file yet; tests run locally with `pytest`.
