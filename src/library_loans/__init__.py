"""Library loans tracker: a local-first MCP server for borrowed books.

Keeps track of loans, holds, and renewals for books borrowed from local
library branches. Everything stays on disk at home - no cloud, no accounts.
"""

from .loans import (
    DEFAULT_LOAN_DAYS,
    HOLD_STATUSES,
    HOLD_TRANSITIONS,
    MAX_RENEWALS,
    Hold,
    Loan,
    LoanError,
    loan_status,
    normalize_title,
    parse_date,
)
from .store import LoanStore

__all__ = [
    "DEFAULT_LOAN_DAYS",
    "HOLD_STATUSES",
    "HOLD_TRANSITIONS",
    "MAX_RENEWALS",
    "Hold",
    "Loan",
    "LoanError",
    "LoanStore",
    "loan_status",
    "normalize_title",
    "parse_date",
]

__version__ = "0.1.0"
