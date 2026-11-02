"""python3 tests/test_auth_release_checks.py; real temporary files, no Docker/HTTP."""

import importlib.util
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "auth_release", Path(__file__).resolve().parents[1] / "deploy/check_auth_release.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "zebra_erpnext").mkdir()
    (root / "zebra_erpnext/client.py").write_text("current")
    overlay = root / "client.py"
    overlay.write_text("current")
    m.check_overlay(root, {"services": {"backend": {"volumes": [f"{overlay}:{m.TARGET}:ro"]}}})
    m.check_overlay(
        root,
        {
            "services": {
                "backend": {
                    "volumes": [{"source": str(overlay), "target": m.TARGET, "read_only": True}]
                }
            }
        },
    )
    m.check_overlay(root, {"services": {"backend": {"volumes": ["sites:/sites"]}}})
    overlay.write_text("stale")
    try:
        m.check_overlay(root, {"services": {"backend": {"volumes": [f"{overlay}:{m.TARGET}:ro"]}}})
    except ValueError:
        pass
    else:
        raise AssertionError("old source mount was allowed to override the new release")
    (root / "zebra_erpnext/api.py").write_text("current-api")
    parent = root / "shadow"
    parent.mkdir()
    (parent / "client.py").write_text("stale")
    try:
        m.check_overlay(
            root,
            {"services": {"backend": {"volumes": [f"{parent}:{str(Path(m.TARGET).parent)}:ro"]}}},
        )
    except ValueError:
        pass
    else:
        raise AssertionError("parent-directory source shadow was allowed")
    overlay.unlink()
    try:
        m.check_overlay(root, {"services": {"backend": {"volumes": [f"{overlay}:{m.TARGET}:ro"]}}})
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("missing production overlay must block release")
print("PASS current mount accepted; stale/missing overlay rejected; unrelated mounts preserved")
