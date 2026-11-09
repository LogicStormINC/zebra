"""Check stale-source safety locally; add --root /app inside a pinned runtime image."""

import argparse
import importlib.util
import os
import py_compile
import struct
import sys
import sysconfig
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path)
args = parser.parse_args()


def checked(path: Path) -> None:
    cached = Path(importlib.util.cache_from_source(str(path)))
    raw = cached.read_bytes()
    assert raw[:4] == importlib.util.MAGIC_NUMBER
    assert struct.unpack("<I", raw[4:8])[0] == 3, "cache must validate the source hash"
    assert raw[8:16] == importlib.util.source_hash(path.read_bytes())


# Same size and mtime: timestamp validation alone would accept the stale value.
with tempfile.TemporaryDirectory() as directory:
    source = Path(directory) / "owned_e1_cache_check.py"
    source.write_text("value = 1\n")
    py_compile.compile(
        str(source), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH
    )
    checked(source)
    cached = Path(importlib.util.cache_from_source(str(source)))
    old_cache, before = cached.read_bytes(), source.stat()
    source.write_text("value = 2\n")
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    source.chmod(0o444)
    Path(directory).chmod(0o555)
    writing = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location(source.stem, source)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.value == 2
        assert cached.read_bytes() == old_cache, "read-only fallback must not rewrite the cache"
    finally:
        sys.dont_write_bytecode = writing
        Path(directory).chmod(0o700)
        source.chmod(0o600)
print("Checked-hash cache rejects changed source with identical size/mtime without cache writes.")

if args.root is not None:
    for path in (
        args.root / "apps/worker/src/zebra_agent_worker/session_process_child.py",
        args.root / "packages/agent-core/src/agent_core/domain/events.py",
        args.root / "packages/agent-storage/src/agent_storage/postgres/force_stop_executors.py",
        Path(sysconfig.get_path("stdlib")) / "typing.py",
    ):
        checked(path)
    print("Runtime workspace and stdlib bytecode hashes match their source under this interpreter.")
