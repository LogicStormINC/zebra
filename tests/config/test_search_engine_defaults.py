import subprocess
from pathlib import Path


def _settings():
    root = Path(__file__).resolve().parents[2]
    return (root / "docker/web-search/config/settings.yml").read_text()


def _engines():
    section = _settings().split("\nengines:\n", 1)[1].split("\nserver:", 1)[0]
    return {block.splitlines()[0]: block for block in section.split("  - name: ")[1:]}


def test_search_defaults_enable_qualified_yahoo_and_keep_bing_explicit():
    engines = _engines()
    assert "disabled: false" in engines["yahoo"]
    assert "disabled: true" in engines["bing"]
    assert "inactive: false" in engines["bing"]
    assert "base_url: https://cn.bing.com" in engines["bing"]


def test_domestic_and_public_wechat_engines_are_selectable_without_poisoning_defaults():
    settings = _settings()
    expected = {"yahoo", "bing", "sogou", "360search", "sogou wechat"}
    kept = settings.split("keep_only: [", 1)[1].split("]", 1)[0]
    assert {name.strip() for name in kept.split(",")} == expected
    engines = _engines()
    assert set(engines) == expected | {"exa"}
    assert "disabled: true" in engines["exa"]
    assert {name for name, e in engines.items() if "disabled: false" in e} == {"yahoo"}
    for name in expected - {"yahoo", "bing"}:
        assert "inactive: false" in engines[name]
        assert "timeout: 5.0" in engines[name]
    assert "shortcut: sogouw" in engines["sogou wechat"]


def test_agent_search_contract_explains_native_engine_selection():
    from agent_tools.search_pipeline import web_search_v2_contract
    from agent_tools.web_search import web_search_contract

    description = web_search_contract.argument_properties["query"]["description"]
    for shortcut in ["!yh", "!bing", "!sogou", "!360so", "!sogouw"]:
        assert shortcut in description
    assert "!bing (default)" not in description
    assert "!bd" not in description and "Baidu" not in description
    assert "public WeChat articles" in description
    assert web_search_v2_contract.argument_properties["query"]["description"] == description


def test_operator_probe_does_not_accept_empty_or_failed_engine_as_ready():
    root = Path(__file__).resolve().parents[2]
    probe = root / "docker/web-search/verify.py"
    completed = subprocess.run(["python3", str(probe), "--help"], capture_output=True)
    assert completed.returncode == 0
    assert b"query" in completed.stdout
