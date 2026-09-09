from scripts.bootstrap_mcp_key import bootstrap


def test_master_key_is_private_and_never_overwritten(tmp_path):
    assert bootstrap(tmp_path)
    path = tmp_path / "master.json"
    original = path.read_bytes()
    assert path.stat().st_mode & 0o077 == 0
    assert not bootstrap(tmp_path)
    assert path.read_bytes() == original
