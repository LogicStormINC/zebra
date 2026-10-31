#!/usr/bin/env python3
"""Runnable assertions. Default: no database writes. --fixture commands: QA only.

Run with Python stdlib, then in exact pinned105 API image for psycopg SQL checks.
The explicitly disposable fixture phases require dedicated QA databases and native
pg_dump/psql pre/postdata between phases; see ERP_DATABASE_TRANSFER.md.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
# isort: split

from check_transfer_contract import checks as checks
from check_transfer_fixture import fixture as fixture

if __name__ == "__main__":
    if len(sys.argv) == 1:
        checks()
    else:
        assert (
            len(sys.argv) == 4
            and sys.argv[1] == "--fixture"
            and sys.argv[2] in ("identity", "prepare", "copy", "verify")
        )
        fixture(sys.argv[2], sys.argv[3])
