from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest


def _load_main_module(monkeypatch):
    class DummyMCP:
        def __init__(self, *_args, **_kwargs):
            pass

        def tool(self, func):
            return func

        def run(self, **_kwargs):
            return None

    dummy_fastmcp = types.ModuleType("fastmcp")
    dummy_fastmcp.FastMCP = DummyMCP
    monkeypatch.setitem(sys.modules, "fastmcp", dummy_fastmcp)
    sys.modules.pop("mineru_mcp_server.main", None)
    return importlib.import_module("mineru_mcp_server.main")


def test_list_pdf_files_supports_recursive(monkeypatch, tmp_path: Path):
    main = _load_main_module(monkeypatch)
    (tmp_path / "a.pdf").write_bytes(b"1")
    nested = tmp_path / "docs" / "lab"
    nested.mkdir(parents=True)
    (nested / "b.pdf").write_bytes(b"2")

    non_recursive = main.list_pdf_files(tmp_path)
    recursive = main.list_pdf_files(tmp_path, recursive=True)

    assert [p.name for p in non_recursive] == ["a.pdf"]
    assert sorted(p.name for p in recursive) == ["a.pdf", "b.pdf"]


def test_normalize_output_format_accepts_md_alias(monkeypatch):
    main = _load_main_module(monkeypatch)

    assert main.normalize_output_format("html") == "html"
    assert main.normalize_output_format("markdown") == "markdown"
    assert main.normalize_output_format("md") == "markdown"


@pytest.mark.parametrize("invalid", ["", "txt", "pdf"])
def test_normalize_output_format_rejects_unknown(monkeypatch, invalid: str):
    main = _load_main_module(monkeypatch)

    with pytest.raises(ValueError):
        main.normalize_output_format(invalid)


def test_build_extra_formats_contains_required_target(monkeypatch):
    main = _load_main_module(monkeypatch)

    markdown_formats = main.build_extra_formats(None, "markdown")
    html_formats = main.build_extra_formats(["json"], "html")

    assert "markdown" in markdown_formats
    assert "html" in markdown_formats
    assert "html" in html_formats


def test_ensure_unique_pdf_names_rejects_duplicates(monkeypatch, tmp_path: Path):
    main = _load_main_module(monkeypatch)
    p1 = tmp_path / "a" / "same.pdf"
    p2 = tmp_path / "b" / "same.pdf"
    p1.parent.mkdir(parents=True)
    p2.parent.mkdir(parents=True)
    p1.write_bytes(b"1")
    p2.write_bytes(b"2")

    with pytest.raises(ValueError):
        main.ensure_unique_pdf_names([p1, p2])
