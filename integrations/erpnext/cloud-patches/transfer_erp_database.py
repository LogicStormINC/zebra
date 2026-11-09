#!/usr/bin/env python3
"""Fail-closed, offline ERP105 namespace transfer. No infrastructure/cutover commands.

Host: inspect CONFIG; transfer CONFIG --approved FILE --fingerprint SHA256.
Worker: private NDJSON protocol; invoked only by the host in the pinned API image.
See ERP_DATABASE_TRANSFER.md. Successful transfer never activates a consumer.
"""

import argparse
import json
import signal
import sys

from transfer_host import (
    Host as Host,
)
from transfer_inventory import (
    API_IMAGE as API_IMAGE,
)
from transfer_inventory import (
    CATALOG_SQL as CATALOG_SQL,
)
from transfer_inventory import (
    CONSUMERS as CONSUMERS,
)
from transfer_inventory import (
    DEFINITION as DEFINITION,
)
from transfer_inventory import (
    DEFINITIONS as DEFINITIONS,
)
from transfer_inventory import (
    IDENTITY_SQL as IDENTITY_SQL,
)
from transfer_inventory import (
    NAMESPACES as NAMESPACES,
)
from transfer_inventory import (
    PG_IMAGE as PG_IMAGE,
)
from transfer_inventory import (
    ROUTINES as ROUTINES,
)
from transfer_inventory import (
    SEQUENCE_OWNERS as SEQUENCE_OWNERS,
)
from transfer_inventory import (
    SESSION_SETTINGS as SESSION_SETTINGS,
)
from transfer_inventory import (
    SOURCE_CONTAINER as SOURCE_CONTAINER,
)
from transfer_inventory import (
    SOURCE_DATABASE as SOURCE_DATABASE,
)
from transfer_inventory import (
    SOURCE_NETWORK as SOURCE_NETWORK,
)
from transfer_inventory import (
    SOURCE_ROLE as SOURCE_ROLE,
)
from transfer_inventory import (
    TABLES as TABLES,
)
from transfer_inventory import (
    TRIGGERS as TRIGGERS,
)
from transfer_protocol import (
    Refusal as Refusal,
)
from transfer_protocol import (
    canonical as canonical,
)
from transfer_protocol import (
    canonical_migrations as canonical_migrations,
)
from transfer_protocol import (
    classify as classify,
)
from transfer_protocol import (
    digest as digest,
)
from transfer_protocol import (
    next_sequence as next_sequence,
)
from transfer_protocol import (
    require as require,
)
from transfer_protocol import (
    secure_read as secure_read,
)
from transfer_protocol import (
    secure_write as secure_write,
)
from transfer_protocol import (
    validate_catalog as validate_catalog,
)
from transfer_protocol import (
    validate_gate as validate_gate,
)
from transfer_protocol import (
    validate_ledger as validate_ledger,
)
from transfer_worker import (
    Worker as Worker,
)
from transfer_worker_entry import (
    worker_main as worker_main,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inspect", "transfer", "worker"))
    parser.add_argument("config")
    parser.add_argument(
        "--disposable-qa",
        action="store_true",
        help="strict labeled isolated QA endpoints only; never production",
    )
    parser.add_argument("--approved")
    parser.add_argument("--fingerprint")
    args = parser.parse_args()
    if args.mode == "worker":
        worker_main(args.config)
        return
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(Refusal("terminated")))
    host = None
    try:
        require(args.mode != "transfer" or args.approved and args.fingerprint, "approval_required")
        host = Host(args.config, args.disposable_qa)
        report = host.execute(args.mode, args.approved, args.fingerprint)
    except BaseException as error:
        print(
            json.dumps(
                {
                    "status": "failed_unactivated",
                    "phase": getattr(host, "phase", "configuration"),
                    "cleanup": getattr(host, "cleanup_report", {}),
                    "reason": str(error) if isinstance(error, Refusal) else "operator_failure",
                    "sqlstate": getattr(error, "sqlstate", None),
                    "consumers_released": False,
                }
            ),
            flush=True,
        )
        sys.exit(1)
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
