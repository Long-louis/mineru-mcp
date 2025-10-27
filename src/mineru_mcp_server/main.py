from __future__ import annotations

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


def list_pdf_files(pdf_folder: Path) -> List[Path]:
    return sorted(path for path in pdf_folder.glob("*.pdf") if path.is_file())


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


def download_and_extract(zip_url: str, file_name: str, config: MineruConfig) -> Dict[str, str]:
    output_folder = config.output_folder
    base_name = Path(file_name).stem
    temp_dir = output_folder / f"__mineru_tmp_{uuid.uuid4().hex}"
    try:
        response = requests.get(zip_url, timeout=600)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            archive.extractall(temp_dir)
        html_file = None
        asset_dirs: List[Path] = []
        for path in temp_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() == ".html":
                html_file = path
            if path.is_dir() and path.name.lower() in {"figure", "images", "assets"}:
                asset_dirs.append(path)
        if not html_file:
            return {
                "file": file_name,
                "stage": "download",
                "status": "error",
                "message": "结果包中未找到 HTML 文件",
            }
        if config.rename_assets:
            rename_assets(asset_dirs, html_file, base_name)
        final_html_path = output_folder / f"{base_name}.html"
        final_html_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(html_file), final_html_path)
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
            "message": f"已保存 {final_html_path.name}",
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


def rename_assets(asset_dirs: List[Path], html_file: Path, base_name: str) -> None:
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
    html_content = html_file.read_text(encoding="utf-8")
    for old, new in rename_map.items():
        html_content = html_content.replace(f'"{old}"', f'"{new}"')
        html_content = html_content.replace(f"'{old}'", f"'{new}'")
    html_file.write_text(html_content, encoding="utf-8")


def poll_results(batch_id: str, config: MineruConfig, expected_files: List[str]) -> List[Dict[str, str]]:
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
                    details.append(download_and_extract(zip_url, file_name, config))
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


@mcp.tool
def convert_pdfs_with_mineru(
    pdf_folder: str,
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
    """批量调用 Mineru API 将 PDF 转为 HTML。"""

    pdf_path = Path(pdf_folder).expanduser()
    output_path = Path(output_folder).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)
    if not pdf_path.exists() or not pdf_path.is_dir():
        raise NotADirectoryError(f"PDF 目录不存在: {pdf_path}")
    token = api_token or os.getenv(API_TOKEN_ENV)
    if not token:
        raise ValueError("缺少 Mineru API Token，请通过参数 api_token 或环境变量 MINERU_API_TOKEN 提供")
    pdf_files = list_pdf_files(pdf_path)
    if not pdf_files:
        return {
            "pdf_total": 0,
            "uploaded": 0,
            "completed": 0,
            "details": [],
            "message": "指定目录下未找到 PDF 文件",
        }
    formats = list(extra_formats) if extra_formats else list(DEFAULT_EXTRA_FORMATS)
    if not any(fmt.lower() == "html" for fmt in formats):
        formats.append("html")
    config = MineruConfig(
        api_token=token,
        pdf_folder=pdf_path,
        output_folder=output_path,
        language=language,
        enable_table=enable_table,
        extra_formats=formats,
        poll_interval=max(1.0, poll_interval),
        max_wait=max(60.0, max_wait),
        rename_assets=rename_assets_flag,
        is_ocr=is_ocr,
    )
    batch_id, upload_map = request_upload_urls(pdf_files, config)
    upload_details = upload_files(upload_map, pdf_files)
    successful_files = [item["file"] for item in upload_details if item["status"] == "success"]
    if not successful_files:
        return {
            "pdf_total": len(pdf_files),
            "uploaded": 0,
            "completed": 0,
            "details": upload_details,
            "message": "所有文件上传失败，请检查日志",
        }
    poll_details = poll_results(batch_id, config, successful_files)
    all_details = upload_details + poll_details
    completed_count = sum(1 for item in poll_details if item["status"] == "success")
    return {
        "pdf_total": len(pdf_files),
        "uploaded": len(successful_files),
        "completed": completed_count,
        "details": all_details,
        "output_directory": str(output_path),
    }


def start_server() -> None:
    mcp.run(
        transport="http",
        host="127.0.0.1",
        port=4399,
        log_level="DEBUG",
    )


if __name__ == "__main__":
    start_server()
