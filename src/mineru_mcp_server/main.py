from __future__ import annotations

import argparse
import io
import os
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from fastmcp import FastMCP

BASE_URL = "https://mineru.net"
API_TOKEN_ENV = "MINERU_API_TOKEN"
DEFAULT_LANGUAGE = "ch"
DEFAULT_POLL_INTERVAL = 3.0
DEFAULT_MAX_WAIT = 1800.0
DEFAULT_EXTRA_FORMATS = ["html"]

mcp = FastMCP("MineruServer")


@dataclass
class MineruConfig:
    api_token: str
    pdf_folder: Path
    output_folder: Path
    language: str
    enable_table: bool
    extra_formats: List[str]
    poll_interval: float
    max_wait: float
    rename_assets: bool
    is_ocr: bool


def list_pdf_files(pdf_folder: Path, recursive: bool = False) -> List[Path]:
    pattern = "**/*.pdf" if recursive else "*.pdf"
    return sorted(path for path in pdf_folder.glob(pattern) if path.is_file())


def normalize_output_format(output_format: str) -> str:
    normalized = output_format.strip().lower()
    if normalized == "md":
        normalized = "markdown"
    if normalized not in {"html", "markdown"}:
        raise ValueError("output_format 仅支持 'html' 或 'markdown'（可使用别名 'md'）")
    return normalized


def build_extra_formats(extra_formats: Optional[List[str]], output_format: str) -> List[str]:
    formats = list(extra_formats) if extra_formats else list(DEFAULT_EXTRA_FORMATS)
    normalized = [fmt.strip().lower() for fmt in formats if fmt and fmt.strip()]
    if "html" not in normalized:
        normalized.append("html")
    if output_format == "markdown" and "markdown" not in normalized:
        normalized.append("markdown")
    return normalized


def ensure_unique_pdf_names(pdf_files: List[Path]) -> None:
    seen = set()
    duplicates = set()
    for path in pdf_files:
        if path.name in seen:
            duplicates.add(path.name)
        seen.add(path.name)
    if duplicates:
        dup_str = ", ".join(sorted(duplicates))
        raise ValueError(
            f"检测到重名 PDF（{dup_str}）。为保证 Mineru 返回结果可正确映射，请先避免同名文件。"
        )


def request_upload_urls(pdf_files: List[Path], config: MineruConfig) -> Tuple[str, Dict[str, str]]:
    payload_files = [{"name": file.name, "is_ocr": config.is_ocr} for file in pdf_files]
    request_body = {
        "enable_table": config.enable_table,
        "language": config.language,
        "extra_formats": config.extra_formats,
        "files": payload_files,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.api_token}",
    }
    url = f"{BASE_URL}/api/v4/file-urls/batch"
    response = requests.post(url, headers=headers, json=request_body, timeout=60)
    response.raise_for_status()
    body = response.json()
    if body.get("code") != 0:
        raise RuntimeError(f"Mineru API 返回错误: {body.get('msg')}")
    data = body.get("data", {})
    batch_id = data.get("batch_id")
    if not batch_id:
        raise RuntimeError("Mineru API 未返回 batch_id")
    file_urls: List[str] = data.get("file_urls") or []
    if len(file_urls) != len(pdf_files):
        raise RuntimeError("获取的上传链接数量与文件数量不匹配")
    upload_map = {file.name: url for file, url in zip(pdf_files, file_urls)}
    return batch_id, upload_map


def upload_files(upload_map: Dict[str, str], pdf_files: List[Path]) -> List[Dict[str, str]]:
    details: List[Dict[str, str]] = []
    for file_path in pdf_files:
        upload_url = upload_map.get(file_path.name)
        if not upload_url:
            details.append(
                {
                    "file": file_path.name,
                    "stage": "upload",
                    "status": "error",
                    "message": "未找到上传链接",
                }
            )
            continue
        try:
            with file_path.open("rb") as handle:
                response = requests.put(upload_url, data=handle, timeout=600)
                response.raise_for_status()
            details.append(
                {
                    "file": file_path.name,
                    "stage": "upload",
                    "status": "success",
                    "message": "上传成功",
                }
            )
        except requests.exceptions.RequestException as exc:
            details.append(
                {
                    "file": file_path.name,
                    "stage": "upload",
                    "status": "error",
                    "message": f"上传失败: {exc}",
                }
            )
    return details


def download_and_extract(
    zip_url: str,
    file_name: str,
    config: MineruConfig,
    output_format: str = "html",
) -> Dict[str, str]:
    output_folder = config.output_folder
    base_name = Path(file_name).stem
    temp_dir = output_folder / f"__mineru_tmp_{uuid.uuid4().hex}"
    try:
        response = requests.get(zip_url, timeout=600)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            archive.extractall(temp_dir)
        html_file = None
        markdown_file = None
        asset_dirs: List[Path] = []
        for path in temp_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() == ".html":
                html_file = path
            if path.is_file() and path.suffix.lower() == ".md":
                markdown_file = path
            if path.is_dir() and path.name.lower() in {"figure", "images", "assets"}:
                asset_dirs.append(path)
        normalized_output_format = normalize_output_format(output_format)
        if normalized_output_format == "html" and not html_file:
            return {
                "file": file_name,
                "stage": "download",
                "status": "error",
                "message": "结果包中未找到 HTML 文件",
            }
        if normalized_output_format == "markdown" and not markdown_file:
            return {
                "file": file_name,
                "stage": "download",
                "status": "error",
                "message": "结果包中未找到 Markdown 文件，请确认 extra_formats 包含 markdown",
            }
        if config.rename_assets:
            text_files = []
            if html_file:
                text_files.append(html_file)
            if markdown_file:
                text_files.append(markdown_file)
            rename_assets(asset_dirs, text_files, base_name)
        final_extension = ".md" if normalized_output_format == "markdown" else ".html"
        final_doc_path = output_folder / f"{base_name}{final_extension}"
        final_doc_path.parent.mkdir(parents=True, exist_ok=True)
        source_doc = markdown_file if normalized_output_format == "markdown" else html_file
        shutil.move(str(source_doc), final_doc_path)
        for asset_dir in asset_dirs:
            if not asset_dir.exists():
                continue
            target_dir = output_folder / asset_dir.name
            if target_dir.exists():
                shutil.copytree(asset_dir, target_dir, dirs_exist_ok=True)
                shutil.rmtree(asset_dir, ignore_errors=True)
            else:
                shutil.move(str(asset_dir), target_dir)
        return {
            "file": file_name,
            "stage": "download",
            "status": "success",
            "message": f"已保存 {final_doc_path.name}",
        }
    except requests.exceptions.RequestException as exc:
        return {
            "file": file_name,
            "stage": "download",
            "status": "error",
            "message": f"下载失败: {exc}",
        }
    except Exception as exc:  # pylint: disable=broad-except
        return {
            "file": file_name,
            "stage": "download",
            "status": "error",
            "message": f"处理结果包失败: {exc}",
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def rename_assets(asset_dirs: List[Path], text_files: List[Path], base_name: str) -> None:
    if not asset_dirs:
        return
    rename_map: Dict[str, str] = {}
    for asset_dir in asset_dirs:
        files = sorted(
            file for file in asset_dir.iterdir() if file.is_file()
        )
        counter = 1
        for file in files:
            extension = file.suffix.lower()
            if extension not in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg"}:
                continue
            new_name = f"{base_name}_{counter}{extension}"
            counter += 1
            new_path = file.with_name(new_name)
            file.rename(new_path)
            relative_old = f"{asset_dir.name}/{file.name}"
            relative_new = f"{asset_dir.name}/{new_name}"
            rename_map[relative_old] = relative_new
    if not rename_map:
        return
    for text_file in text_files:
        text_content = text_file.read_text(encoding="utf-8")
        for old, new in rename_map.items():
            text_content = text_content.replace(f'"{old}"', f'"{new}"')
            text_content = text_content.replace(f"'{old}'", f"'{new}'")
        text_file.write_text(text_content, encoding="utf-8")


def poll_results(
    batch_id: str,
    config: MineruConfig,
    expected_files: List[str],
    output_format: str = "html",
) -> List[Dict[str, str]]:
    details: List[Dict[str, str]] = []
    completed: Dict[str, bool] = {name: False for name in expected_files}
    headers = {"Authorization": f"Bearer {config.api_token}"}
    url = f"{BASE_URL}/api/v4/extract-results/batch/{batch_id}"
    deadline = time.monotonic() + config.max_wait
    while not all(completed.values()) and time.monotonic() < deadline:
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 0:
            raise RuntimeError(f"Mineru 状态接口返回错误: {body.get('msg')}")
        extract_results = body.get("data", {}).get("extract_result", [])
        for result in extract_results:
            file_name = result.get("file_name")
            if not file_name or file_name not in completed or completed[file_name]:
                continue
            state = result.get("state")
            if state == "done":
                zip_url = result.get("full_zip_url")
                if not zip_url:
                    details.append(
                        {
                            "file": file_name,
                            "stage": "download",
                            "status": "error",
                            "message": "状态为 done 但未提供下载链接",
                        }
                    )
                else:
                    details.append(download_and_extract(zip_url, file_name, config, output_format))
                completed[file_name] = True
            elif state == "failed":
                message = result.get("err_msg") or "未知错误"
                details.append(
                    {
                        "file": file_name,
                        "stage": "convert",
                        "status": "error",
                        "message": message,
                    }
                )
                completed[file_name] = True
        if not all(completed.values()):
            time.sleep(config.poll_interval)
    for file_name, is_done in completed.items():
        if not is_done:
            details.append(
                {
                    "file": file_name,
                    "stage": "convert",
                    "status": "error",
                    "message": "超时未完成",
                }
            )
    return details


def parse_cli_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Mineru MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="MCP transport mode. Use stdio for mcp.json command mode.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host when transport=http")
    parser.add_argument("--port", type=int, default=4399, help="Port when transport=http")
    parser.add_argument("--log-level", default="DEBUG", help="FastMCP log level")
    return parser.parse_args(argv)


def run_server(*, transport: str, host: str, port: int, log_level: str) -> None:
    run_kwargs = {
        "transport": transport,
        "log_level": log_level,
    }
    if transport == "http":
        run_kwargs["host"] = host
        run_kwargs["port"] = port
    mcp.run(**run_kwargs)


def convert_pdf_files_with_mineru(
    *,
    pdf_files: List[Path],
    output_folder: str,
    api_token: Optional[str],
    source_folder: Optional[Path] = None,
    language: str = DEFAULT_LANGUAGE,
    enable_table: bool = True,
    extra_formats: Optional[List[str]] = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    max_wait: float = DEFAULT_MAX_WAIT,
    rename_assets_flag: bool = True,
    is_ocr: bool = True,
    output_format: str = "markdown",
    check_duplicate_names: bool = False,
) -> Dict[str, object]:
    output_path = Path(output_folder).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)
    token = api_token or os.getenv(API_TOKEN_ENV)
    if not token:
        raise ValueError("缺少 Mineru API Token，请通过参数 api_token 或环境变量 MINERU_API_TOKEN 提供")
    normalized_output_format = normalize_output_format(output_format)
    normalized_pdf_files = sorted(path.expanduser() for path in pdf_files)
    if not normalized_pdf_files:
        return {
            "pdf_total": 0,
            "uploaded": 0,
            "completed": 0,
            "details": [],
            "message": "未找到可转换的 PDF 文件",
        }
    for pdf_file in normalized_pdf_files:
        if not pdf_file.exists() or not pdf_file.is_file():
            raise FileNotFoundError(f"PDF 文件不存在: {pdf_file}")
        if pdf_file.suffix.lower() != ".pdf":
            raise ValueError(f"只支持 PDF 文件，收到: {pdf_file.name}")
    if check_duplicate_names:
        ensure_unique_pdf_names(normalized_pdf_files)
    formats = build_extra_formats(extra_formats, normalized_output_format)
    config_pdf_folder = source_folder.expanduser() if source_folder else normalized_pdf_files[0].parent
    config = MineruConfig(
        api_token=token,
        pdf_folder=config_pdf_folder,
        output_folder=output_path,
        language=language,
        enable_table=enable_table,
        extra_formats=formats,
        poll_interval=max(1.0, poll_interval),
        max_wait=max(60.0, max_wait),
        rename_assets=rename_assets_flag,
        is_ocr=is_ocr,
    )
    batch_id, upload_map = request_upload_urls(normalized_pdf_files, config)
    upload_details = upload_files(upload_map, normalized_pdf_files)
    successful_files = [item["file"] for item in upload_details if item["status"] == "success"]
    if not successful_files:
        return {
            "pdf_total": len(normalized_pdf_files),
            "uploaded": 0,
            "completed": 0,
            "details": upload_details,
            "message": "所有文件上传失败，请检查日志",
        }
    poll_details = poll_results(batch_id, config, successful_files, normalized_output_format)
    all_details = upload_details + poll_details
    completed_count = sum(1 for item in poll_details if item["status"] == "success")
    return {
        "pdf_total": len(normalized_pdf_files),
        "uploaded": len(successful_files),
        "completed": completed_count,
        "details": all_details,
        "output_directory": str(output_path),
    }


@mcp.tool
def convert_single_pdf_to_markdown(
    pdf_path: str,
    output_folder: str,
    api_token: Optional[str] = None,
    language: str = DEFAULT_LANGUAGE,
    enable_table: bool = True,
    extra_formats: Optional[List[str]] = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    max_wait: float = DEFAULT_MAX_WAIT,
    rename_assets_flag: bool = True,
    is_ocr: bool = True,
) -> Dict[str, object]:
    """按单个 PDF 文件路径上传并转换为 Markdown。"""

    single_pdf = Path(pdf_path).expanduser()
    if not single_pdf.exists() or not single_pdf.is_file():
        raise FileNotFoundError(f"PDF 文件不存在: {single_pdf}")
    if single_pdf.suffix.lower() != ".pdf":
        raise ValueError(f"只支持 PDF 文件，收到: {single_pdf.name}")
    return convert_pdf_files_with_mineru(
        pdf_files=[single_pdf],
        output_folder=output_folder,
        api_token=api_token,
        source_folder=single_pdf.parent,
        language=language,
        enable_table=enable_table,
        extra_formats=extra_formats,
        poll_interval=poll_interval,
        max_wait=max_wait,
        rename_assets_flag=rename_assets_flag,
        is_ocr=is_ocr,
        output_format="markdown",
        check_duplicate_names=False,
    )


@mcp.tool
def convert_repo_pdfs_to_markdown(
    repo_folder: str,
    output_folder: str,
    api_token: Optional[str] = None,
    language: str = DEFAULT_LANGUAGE,
    enable_table: bool = True,
    extra_formats: Optional[List[str]] = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    max_wait: float = DEFAULT_MAX_WAIT,
    rename_assets_flag: bool = True,
    is_ocr: bool = True,
) -> Dict[str, object]:
    """递归扫描仓库目录中的 PDF，并批量转换为 Markdown。"""

    repo_path = Path(repo_folder).expanduser()
    if not repo_path.exists() or not repo_path.is_dir():
        raise NotADirectoryError(f"仓库目录不存在: {repo_path}")
    pdf_files = list_pdf_files(repo_path, recursive=True)
    return convert_pdf_files_with_mineru(
        pdf_files=pdf_files,
        output_folder=output_folder,
        api_token=api_token,
        source_folder=repo_path,
        language=language,
        enable_table=enable_table,
        extra_formats=extra_formats,
        poll_interval=poll_interval,
        max_wait=max_wait,
        rename_assets_flag=rename_assets_flag,
        is_ocr=is_ocr,
        output_format="markdown",
        check_duplicate_names=True,
    )


def start_server(argv: Optional[List[str]] = None) -> None:
    args = parse_cli_args(argv)
    run_server(
        transport=args.transport,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    start_server()
