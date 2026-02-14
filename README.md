# Mineru MCP 服务端

将 Mineru 官方 PDF 解析能力封装为 FastMCP 服务，便于任意支持 MCP 协议的客户端调用，实现 PDF 转 Markdown（含图片资源整理与命名）。

## 功能亮点
- 自动扫描指定目录下的 PDF 文件并批量上传至 Mineru
- 支持自定义语言、表格识别开关、额外输出格式等参数
- 下载 Mineru 返回的 ZIP 结果，自动整理 HTML 与图片资源，支持按文件名规则重命名
- 通过 FastMCP 暴露两个语义清晰工具：`convert_single_pdf_to_markdown` 与 `convert_repo_pdfs_to_markdown`

## 环境要求
- Python 3.10 及以上版本
- 可访问 `https://mineru.net` 的网络环境
- Mineru API Token（可通过参数或环境变量 `MINERU_API_TOKEN` 提供）

## 安装步骤（本地开发）
```powershell
cd main/mineru_mcp_project
pip install -e .
```

## 配置 API Token
```powershell
# PowerShell 示例
$env:MINERU_API_TOKEN = "你的 Mineru Token"
```
也可在调用工具时通过 `api_token` 参数显式传入。

## 启动服务

### 方式一：本地已安装包
```powershell
mineru-mcp-server
```

默认以 `stdio` 传输启动（适配 `mcp.json` command 模式）。

如果你要手动跑 HTTP 模式：
```powershell
mineru-mcp-server --transport http --host 127.0.0.1 --port 4399
```

### 方式二：`uvx` 一键运行（推荐给 MCP 客户端配置）
```powershell
uvx --from git+https://github.com/<your-account>/<your-repo> mineru-mcp-server
```

## mcp.json 一键配置示例
```json
{
  "mcpServers": {
    "mineru": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/<your-account>/<your-repo>",
        "mineru-mcp-server"
      ],
      "env": {
        "MINERU_API_TOKEN": "你的 Mineru Token"
      }
    }
  }
}
```

## 工具一：convert_single_pdf_to_markdown

用于直接指定一个 PDF 路径转换 Markdown（不需要手动复制到单独目录）。

| 参数 | 类型 | 默认值 | 说明 |
| ---- | ---- | ------ | ---- |
| `pdf_path` | str | – | 单个 PDF 文件路径（必填） |
| `output_folder` | str | – | 转换结果输出目录（必填） |
| `api_token` | str | `None` | 可选，若未提供则读取环境变量 `MINERU_API_TOKEN` |
| `language` | str | `"ch"` | Mineru 解析语言参数 |
| `enable_table` | bool | `True` | 是否启用表格识别 |
| `extra_formats` | list[str] | `None` | 额外导出格式，会自动补齐 `markdown` 与 `html` |
| `poll_interval` | float | `3.0` | 轮询任务状态的时间间隔（秒） |
| `max_wait` | float | `1800.0` | 单批任务最大等待时间（秒） |
| `rename_assets_flag` | bool | `True` | 是否重命名图片资源并同步更新引用 |
| `is_ocr` | bool | `True` | 上传 Mineru 时的 OCR 开关 |

## 工具二：convert_repo_pdfs_to_markdown

用于递归扫描代码仓库里的 PDF 并批量转 Markdown。

| 参数 | 类型 | 默认值 | 说明 |
| ---- | ---- | ------ | ---- |
| `repo_folder` | str | – | 仓库根目录路径（必填） |
| `output_folder` | str | – | 转换结果输出目录（必填） |
| `api_token` | str | `None` | 可选，若未提供则读取环境变量 `MINERU_API_TOKEN` |
| `language` | str | `"ch"` | Mineru 解析语言参数 |
| `enable_table` | bool | `True` | 是否启用表格识别 |
| `extra_formats` | list[str] | `None` | 额外导出格式，会自动补齐 `markdown` 与 `html` |
| `poll_interval` | float | `3.0` | 轮询任务状态的时间间隔（秒） |
| `max_wait` | float | `1800.0` | 单批任务最大等待时间（秒） |
| `rename_assets_flag` | bool | `True` | 是否重命名图片资源并同步更新引用 |
| `is_ocr` | bool | `True` | 上传 Mineru 时的 OCR 开关 |

> 递归模式下，当前版本要求 PDF 文件名不能重名（不同目录下不能同时存在同名 `xxx.pdf`）。

### 返回结构示例
```json
{
  "pdf_total": 12,
  "uploaded": 12,
  "completed": 12,
  "output_directory": "D:/Mineru/output",
  "details": [
    {"file": "sample.pdf", "stage": "upload", "status": "success", "message": "上传成功"},
    {"file": "sample.pdf", "stage": "download", "status": "success", "message": "已保存 sample.md"}
  ]
}
```

## 调用 Demo（FastMCP Client）
```python
import asyncio
from fastmcp import Client

client = Client("http://127.0.0.1:4399/mcp/")

async def main():
    async with client:
        result = await client.call_tool(
            "convert_single_pdf_to_markdown",
            {
                "pdf_path": r"D:\\Docs\\pdf\\lab1.pdf",
                "output_folder": r"D:\\Docs\\md",
                "poll_interval": 5.0,
                "max_wait": 3600.0
            }
        )
        print(result.data)

if __name__ == "__main__":
    asyncio.run(main())
```

## 快速验证
1. 准备 PDF 并确保 Token 可用
2. 执行 `mineru-mcp-server` 启动服务（或使用上面的 `uvx` 命令）
3. 使用 MCP 客户端触发 `convert_single_pdf_to_markdown` 或 `convert_repo_pdfs_to_markdown`
4. 在 `output_folder` 查看生成的 `.md` 及图片资源

## 仓库内 PDF 直接转 Markdown（无需手动复制）
如果你的代码仓库里散落着实验说明 PDF，可以直接递归转换：

```json
{
  "repo_folder": "/path/to/your/repo",
  "output_folder": "/path/to/your/repo/.mineru-output",
  "poll_interval": 5.0,
  "max_wait": 3600.0
}
```

## 常见问题
- **上传失败**：检查 Token 是否有效、网络是否通畅，或文件是否过大
- **转换超时**：适当增大 `max_wait`，或缩小单次批量文件数量
- **资源未重命名**：将 `rename_assets_flag` 设为 `True`，并确认 ZIP 内存在 `figure`/`images` 等资源文件夹
