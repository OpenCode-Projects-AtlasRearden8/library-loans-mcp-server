# Library Loans MCP Server

A small, local-first MCP server that keeps track of the books you borrow from
your public library branches. Record loans when you check books out, track
holds while you wait your turn, renew when you get to, and ask simple
questions any time: *what's due soon? what's overdue? how do things look per
branch?* The answers come back as plain, readable text that you (or an AI
agent) can act on directly.

Everything lives in one JSON file on your own disk. There is no cloud, no
account, and nothing to install beyond Python and the official `mcp` package.

## What it is not

This project is about *borrowed physical books and their logistics*. It is
distinct from:

- **reading-room-mcp-server** - reading notes and content you already own
  (highlights, annotations, what the book *said*).
- **dates-to-remember-mcp-server** - general-purpose date reminders
  (birthdays, appointments, deadlines of every kind).

Library-loans is purely for the borrowed-copy lifecycle: checked out, due,
renewed, returned, hold placed, hold ready, picked up.

## Tools

| Tool | What it does |
| --- | --- |
| `record_loan` | Save a checkout: title, author, branch, checkout date, due date (defaults: today, +21 days) |
| `renew_loan` | Push the due date out (renews from the current due date; blocked when overdue, out of renewals, or a hold waits on the title) |
| `return_loan` | Mark a loan returned so it stops showing up in queries |
| `list_loans` | All loans, or just active ones, with status marks |
| `due_soon` | Loans due within the next N days (default 7) |
| `list_overdue` | Loans past their due date, most urgent first |
| `branch_tallies` | Per-branch counts: active loans, due soon, overdue, open holds |
| `place_hold` | Add a hold (waiting) for a title at a branch; one active hold per title per branch |
| `update_hold` | Move a hold along: `waiting` -> `ready` -> `picked_up` |
| `cancel_hold` | Cancel a hold (final state) |
| `list_holds` | All holds, optionally filtered by status |

House rules an agent can rely on:

- Renewals extend **from the current due date**, never from today.
- A loan can be renewed at most **2 times**, and never while it is overdue.
- An active hold (waiting or ready) on the same title blocks renewal - someone
  is waiting for that copy.
- Hold statuses only move forward; `picked_up` and `cancelled` are final.

## Getting started

Requires Python 3.10+.

```bash
pip install -e .
# or: pip install mcp and run the module directly from the repo
```

Data lives in one JSON file. Set its location before starting the server:

```bash
export LIBRARY_LOANS_PATH="$HOME/library-loans/loans.json"
```

Then add the server to your MCP client (opencode, Claude Desktop, anything
that speaks MCP):

```json
{
  "mcpServers": {
    "library-loans": {
      "command": "python",
      "args": ["-m", "library_loans.server"],
      "env": { "LIBRARY_LOANS_PATH": "/home/you/library-loans/loans.json" }
    }
  }
}
```

A typical conversation:

> "Record that I checked out The Hidden Life of Trees at Northgate today."
> "What's due in the next week?"
> "Where do things stand across my branches?"

The tool results are plain text with status marks like `[OVERDUE]` and
`[due soon]`, plus per-branch tallies, so an agent can summarize and suggest
next steps without parsing anything exotic.

## Privacy

All data stays in the local JSON file you point it at. Nothing is uploaded,
no metrics are collected, and there is nothing to sign into. Delete the file
and your data is gone. Don't put names of family members into the title or
author fields you don't want sitting in plaintext on disk - this is a plain
JSON file, treat it like any other local document.

## Development

```bash
python -m pytest tests/ -v
```

Tests use a frozen "today" date and a throwaway JSON file, so they are
deterministic and never touch real data.

## Changelog summary

- 0.1.0 - First version: loans, holds, renewals, due-soon/overdue queries,
  and per-branch tallies.

## About the maker

**Library Loans MCP Server** is brought to you by [Asdale Dynamics, LLC](https://dylanasdale.github.io) - the publishing/company hub behind
Dylan Asdale's plain-English AI books and beginner-friendly tools. Like
everything at Asdale Dynamics, it's local-first, respects your privacy, and
is designed for people who want AI explained like a friend would: step by
step, never condescending.

## License

MIT - see [LICENSE](LICENSE). Copyright (c) 2026 Asdale Dynamics, LLC.
