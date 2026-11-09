#!/usr/bin/env python3
"""Build review overlays from verified local image config identities.

Run on the Docker host that already holds both captured base images. No pull,
service restart, migration, environment-file loading, or credentials are involved.
"""

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASES = {
    "api": "sha256:2156443eea6ad9330853d16ece204dfa0995a41e5b5b677063386216797daaef",
    "worker": "sha256:33b93abc4b257d0639730f2e2c388d765f092d7979a03b117f6387b0049c0e18",
}


def image_id(reference):
    return subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", reference], text=True
    ).strip()


def require_image(reference, expected):
    if image_id(reference) != expected:
        raise SystemExit(f"Refusing mismatched local base: {reference}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("api", "worker", "all"), default="all")
    parser.add_argument(
        "--stage",
        choices=("initial", "followup", "legacy", "fresh"),
        default="followup",
        help="review image tag suffix",
    )
    parser.add_argument(
        "--check-only", action="store_true", help="verify local bases without tagging/building"
    )
    args = parser.parse_args()
    roles = tuple(BASES) if args.role == "all" else (args.role,)
    # Complete every read-only identity check before any tag/build mutation.
    for role in roles:
        require_image(BASES[role], BASES[role])
        base_tag = f"erpnext-agent-{role}-base:{BASES[role].removeprefix('sha256:')}"
        first = (ROOT / f"Dockerfile.{role}").read_text().splitlines()[0]
        if first != f"FROM {base_tag}":
            raise SystemExit(f"Refusing Dockerfile base drift: {role}")
    if args.check_only:
        print("PASS captured local base identities and Dockerfile references")
        return
    for role in roles:
        expected = BASES[role]
        base_tag = f"erpnext-agent-{role}-base:{expected.removeprefix('sha256:')}"
        subprocess.run(["docker", "image", "tag", expected, base_tag], check=True)
        require_image(base_tag, expected)
        target = (
            f"erpnext-agent-{role}:fresh-authority-review"
            if args.stage == "fresh"
            else f"erpnext-agent-{role}:legacy-containment-review"
            if args.stage == "legacy"
            else f"erpnext-agent-{role}:http-input-{args.stage}-review"
        )
        subprocess.run(
            [
                "docker",
                "build",
                "--pull=false",
                "--network=none",
                "--file",
                str(ROOT / f"Dockerfile.{role}"),
                "--tag",
                target,
                str(ROOT),
            ],
            check=True,
        )
        print(f"BUILT {target} {image_id(target)}")


if __name__ == "__main__":
    main()
