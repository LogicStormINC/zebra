"""Create one operator MCP master key exclusively; never rotate an existing key.

Run as the target container user in a dedicated key directory. Key bytes are
never printed. Mount the resulting directory read-only in API/Worker only.
"""

import argparse
import base64
import json
import os
from pathlib import Path


def bootstrap(root: Path) -> bool:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = root / "master.json"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError("Existing key file is insecure") from None
        value = json.loads(path.read_text())
        if (value.get("version") != "v1"
                or len(base64.b64decode(value["value"], validate=True)) != 32):
            raise ValueError("Existing key file is invalid") from None
        return False
    with os.fdopen(descriptor, "w") as output:
        json.dump({"version": "v1", "value": base64.b64encode(os.urandom(32)).decode()}, output)
        output.flush()
        os.fsync(output.fileno())
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print("Operator key created" if bootstrap(args.directory) else "Existing operator key retained")
