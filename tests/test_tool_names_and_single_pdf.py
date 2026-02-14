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


def test_new_tool_names_exist(monkeypatch):
    main = _load_main_module(monkeypatch)

    assert hasattr(main, "convert_single_pdf_to_markdown")
    assert hasattr(main, "convert_repo_pdfs_to_markdown")
    assert not hasattr(main, "convert_pdfs_with_mineru")


def test_convert_single_pdf_to_markdown_rejects_non_pdf(monkeypatch, tmp_path: Path):
    main = _load_main_module(monkeypatch)
    txt_file = tmp_path / "note.txt"
    txt_file.write_text("x", encoding="utf-8")

    with pytest.raises(ValueError):
        main.convert_single_pdf_to_markdown(
            pdf_path=str(txt_file),
            output_folder=str(tmp_path / "out"),
            api_token="token",
        )


def test_convert_single_pdf_to_markdown_forwards_single_file(monkeypatch, tmp_path: Path):
    main = _load_main_module(monkeypatch)
    pdf_file = tmp_path / "doc.pdf"
    pdf_file.write_bytes(b"pdf")
    captured = {}

    def fake_convert_pdf_files_with_mineru(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(main, "convert_pdf_files_with_mineru", fake_convert_pdf_files_with_mineru)

    result = main.convert_single_pdf_to_markdown(
        pdf_path=str(pdf_file),
        output_folder=str(tmp_path / "out"),
        api_token="token",
    )

    assert result == {"ok": True}
    assert captured["pdf_files"] == [pdf_file]
    assert captured["output_format"] == "markdown"


def test_convert_repo_pdfs_to_markdown_scans_recursively(monkeypatch, tmp_path: Path):
    main = _load_main_module(monkeypatch)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    pdf_file = nested / "lab.pdf"
    pdf_file.write_bytes(b"pdf")
    captured = {}

    def fake_convert_pdf_files_with_mineru(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(main, "convert_pdf_files_with_mineru", fake_convert_pdf_files_with_mineru)

    result = main.convert_repo_pdfs_to_markdown(
        repo_folder=str(tmp_path),
        output_folder=str(tmp_path / "out"),
        api_token="token",
    )

    assert result == {"ok": True}
    assert captured["pdf_files"] == [pdf_file]
    assert captured["output_format"] == "markdown"
