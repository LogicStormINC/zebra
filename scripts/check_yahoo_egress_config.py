"""Native Yahoo engine proxy opt-in compatibility check; no network or credentials."""

import importlib.util
import os
from pathlib import Path

from searx.network.network import Network

source = Path("/usr/local/searxng/searx/engines/yahoo.py")
key = "SEARXNG_YAHOO_PROXY"
original = os.environ.pop(key, None)


def load():
    spec = importlib.util.spec_from_file_location("yahoo_egress_config_check", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    assert not hasattr(load(), "proxies"), "default outgoing proxy was overridden"
    endpoint = "socks5h://127.0.0.1:18446"
    os.environ[key] = endpoint
    engine = load()
    assert engine.proxies == endpoint
    assert list(Network(proxies=engine.proxies).iter_proxies()) == [("all://", [endpoint])]
    os.environ[key] = ""
    assert not hasattr(load(), "proxies"), "empty opt-in should preserve defaults"
    print("PASS: explicit Yahoo-only native proxy opt-in; unset/empty preserve defaults")
finally:
    os.environ.pop(key, None)
    if original is not None:
        os.environ[key] = original
