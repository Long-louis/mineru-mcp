from __future__ import annotations

import importlib
import sys
import types


def _load_main_module(monkeypatch):
    class DummyMCP:
        def __init__(self, *_args, **_kwargs):
            self.calls = []

        def tool(self, func):
            return func

        def run(self, **kwargs):
            self.calls.append(kwargs)

    dummy_fastmcp = types.ModuleType("fastmcp")
    dummy_fastmcp.FastMCP = DummyMCP
    monkeypatch.setitem(sys.modules, "fastmcp", dummy_fastmcp)
    sys.modules.pop("mineru_mcp_server.main", None)
    return importlib.import_module("mineru_mcp_server.main")


def test_parse_cli_args_defaults_to_stdio(monkeypatch):
    main = _load_main_module(monkeypatch)

    args = main.parse_cli_args([])

    assert args.transport == "stdio"
    assert args.host == "127.0.0.1"
    assert args.port == 4399
    assert args.log_level == "DEBUG"


def test_parse_cli_args_accepts_http_options(monkeypatch):
    main = _load_main_module(monkeypatch)

    args = main.parse_cli_args(
        ["--transport", "http", "--host", "0.0.0.0", "--port", "9000", "--log-level", "INFO"]
    )

    assert args.transport == "http"
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.log_level == "INFO"


def test_start_server_forwards_parsed_args_to_mcp_run(monkeypatch):
    main = _load_main_module(monkeypatch)
    captured = {}

    def fake_run_server(*, transport: str, host: str, port: int, log_level: str):
        captured["transport"] = transport
        captured["host"] = host
        captured["port"] = port
        captured["log_level"] = log_level

    monkeypatch.setattr(main, "run_server", fake_run_server)

    main.start_server(["--transport", "http", "--host", "0.0.0.0", "--port", "8088", "--log-level", "INFO"])

    assert captured == {
        "transport": "http",
        "host": "0.0.0.0",
        "port": 8088,
        "log_level": "INFO",
    }
