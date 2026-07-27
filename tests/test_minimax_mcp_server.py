from __future__ import annotations

import importlib.util
from pathlib import Path

PNG = b"\x89PNG\r\n\x1a\nZEBRA-MINIMAX"


def test_understand_image_requires_an_injected_task_root(monkeypatch) -> None:
    module = _module()
    errors: list[str] = []
    calls: list[object] = []
    server = module.MiniMaxMcpServer("key", "https://api.minimaxi.com")
    monkeypatch.delenv("ZEBRA_WORKSPACE_ROOT", raising=False)
    monkeypatch.setattr(module, "_send_error", lambda _id, _code, message: errors.append(message))
    monkeypatch.setattr(server, "_post", lambda *_args: calls.append(_args))

    server._call_understand_image(1, {"prompt": "Read it.", "image_source": "image.png"})

    assert errors == ["ZEBRA_WORKSPACE_ROOT is required for image analysis"]
    assert calls == []


def test_understand_image_rejects_outside_and_symlink_sources_before_egress(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _module()
    root = tmp_path / "task-root"
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    (root / "linked.png").symlink_to(outside)
    errors: list[str] = []
    calls: list[object] = []
    server = module.MiniMaxMcpServer("key", "https://api.minimaxi.com")
    monkeypatch.setenv("ZEBRA_WORKSPACE_ROOT", str(root))
    monkeypatch.setattr(module, "_send_error", lambda _id, _code, message: errors.append(message))
    monkeypatch.setattr(server, "_post", lambda *_args: calls.append(_args))

    server._call_understand_image(1, {"prompt": "Read it.", "image_source": "../outside.png"})
    server._call_understand_image(2, {"prompt": "Read it.", "image_source": "linked.png"})

    assert any("resolve inside the workspace" in error for error in errors)
    assert any("must not be a symlink" in error for error in errors)
    assert calls == []


def test_understand_image_rejects_bad_magic_and_oversize_before_egress(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _module()
    root = tmp_path / "task-root"
    root.mkdir()
    (root / "bad.png").write_bytes(b"not-a-png")
    (root / "large.png").write_bytes(PNG + b"x")
    errors: list[str] = []
    calls: list[object] = []
    server = module.MiniMaxMcpServer("key", "https://api.minimaxi.com")
    monkeypatch.setenv("ZEBRA_WORKSPACE_ROOT", str(root))
    monkeypatch.setattr(module, "_MAX_IMAGE_BYTES", len(PNG))
    monkeypatch.setattr(module, "_send_error", lambda _id, _code, message: errors.append(message))
    monkeypatch.setattr(server, "_post", lambda *_args: calls.append(_args))

    server._call_understand_image(1, {"prompt": "Read it.", "image_source": "bad.png"})
    server._call_understand_image(2, {"prompt": "Read it.", "image_source": "large.png"})

    assert any("invalid image magic bytes" in error for error in errors)
    assert any("exceeds the 20 MB limit" in error for error in errors)
    assert calls == []


def _module():
    path = Path(__file__).parents[1] / "scripts" / "minimax_mcp_server.py"
    spec = importlib.util.spec_from_file_location("test_minimax_mcp_server_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
