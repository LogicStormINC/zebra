from __future__ import annotations

import sys

from zebra_agent_cli.cli import main as cli_main


def main() -> None:
    raise SystemExit(cli_main(sys.argv[1:]))
