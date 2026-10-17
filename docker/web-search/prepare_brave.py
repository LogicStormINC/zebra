"""Prepare private optional settings; never start services or contact a provider."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path


def render_settings(source: str, key: str) -> str:
    if not key or len(key) > 4096 or any(not 33 <= ord(char) <= 126 for char in key):
        raise ValueError("API key must contain 1–4096 printable non-space ASCII characters")
    marker = "\nengines:\n"
    if source.count(marker) != 1 or "braveapi" in source:
        raise ValueError("review base engine configuration before preparing Brave settings")
    # ponytail: one anchored insertion preserves base settings without a YAML dependency.
    # If the base engine layout changes, fail above and review this insertion.
    engine = (
        "  - name: braveapi\n"
        "    engine: braveapi\n"
        "    shortcut: brapi\n"
        "    disabled: true\n"
        "    inactive: false\n"
        "    timeout: 5.0\n"
        "    results_per_page: 20\n"
        f"    api_key: {json.dumps(key)}\n"
    )
    return source.replace(marker, marker + engine)


def write_settings(output: Path, content: str) -> None:
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Exclusive creation refuses an existing file or symlink; rotation is operator-owned.
    with open(output, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as handle:
        handle.write(content)


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--key-file", type=Path, help="Read key from a private file instead of a prompt"
    )
    parser.add_argument("--output", type=Path, default=here / "secrets/brave-settings.yml")
    args = parser.parse_args()
    try:
        key = (
            args.key_file.read_text().rstrip("\r\n")
            if args.key_file
            else getpass.getpass("Brave API key: ")
        )
        content = render_settings((here / "settings.yml").read_text(), key)
        write_settings(args.output, content)
    except (OSError, ValueError) as error:
        # Do not echo exception text: file paths and provider credentials stay private.
        parser.exit(
            1,
            f"Preparation failed ({type(error).__name__}); "
            "check key, base settings and output existence.\n",
        )
    print("Private settings prepared; Yahoo remains default. No services changed.")


if __name__ == "__main__":
    main()
