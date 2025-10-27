# Mineru MCP 服务端

将 Mineru 官方 PDF 解析能力封装为 FastMCP 服务，便于任意支持 MCP 协议的客户端调用，实现批量 PDF 转 HTML（含图片资源整理与命名）。

## 功能亮点
- 自动扫描指定目录下的 PDF 文件并批量上传至 Mineru
- 支持自定义语言、表格识别开关、额外输出格式等参数
- 下载 Mineru 返回的 ZIP 结果，自动整理 HTML 与图片资源，支持按文件名规则重命名
- 通过 FastMCP 暴露 `convert_pdfs_with_mineru` 工具，可直接被主流大模型代理调用

## 环境要求
- Python 3.10 及以上版本
- 可访问 `https://mineru.net` 的网络环境
- Mineru API Token（可通过参数或环境变量 `MINERU_API_TOKEN` 提供）

## 安装步骤
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
```powershell
run-mineru-mcp
```
服务默认监听本地 `http://127.0.0.1:4399/mcp/`。

## 工具：convert_pdfs_with_mineru

| 参数 | 类型 | 默认值 | 说明 |
| ---- | ---- | ------ | ---- |
| `pdf_folder` | str | – | PDF 文件所在目录（必填） |
| `output_folder` | str | – | 转换结果输出目录（必填） |
| `api_token` | str | `None` | 可选，若未提供则读取环境变量 `MINERU_API_TOKEN` |
| `language` | str | `"ch"` | Mineru 解析语言参数 |
| `enable_table` | bool | `True` | 是否启用表格识别 |
| `extra_formats` | list[str] | `["html"]` | Mineru 额外导出格式列表，应包含 `html` |
| `poll_interval` | float | `3.0` | 轮询任务状态的时间间隔（秒） |
| `max_wait` | float | `1800.0` | 单批任务的最大等待时间（秒） |
| `rename_assets_flag` | bool | `True` | 是否对返回的图片资源重命名并同步更新 HTML 引用 |
| `is_ocr` | bool | `True` | 上传 Mineru 时的 OCR 开关 |

### 返回结构示例
```json
{
  "pdf_total": 12,
  "uploaded": 12,
  "completed": 12,
  "output_directory": "D:/Mineru/output",
  "details": [
    {"file": "sample.pdf", "stage": "upload", "status": "success", "message": "上传成功"},
    {"file": "sample.pdf", "stage": "download", "status": "success", "message": "已保存 sample.html"}
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
            "convert_pdfs_with_mineru",
            {
                "pdf_folder": r"D:\\Docs\\pdf",
                "output_folder": r"D:\\Docs\\html",
                "poll_interval": 5.0,
                "max_wait": 3600.0
            }
        )
        print(result.data)

if __name__ == "__main__":
    asyncio.run(main())
```

## 快速验证
1. 准备若干 PDF 放入目标目录，并确保 Token 可用
2. 执行 `run-mineru-mcp` 启动服务
3. 使用上述 Demo 或 MCP 兼容客户端触发 `convert_pdfs_with_mineru`
4. 在 `output_folder` 查看生成的 HTML 及图片资源

## 常见问题
- **上传失败**：检查 Token 是否有效、网络是否通畅，或文件是否过大
- **转换超时**：适当增大 `max_wait`，或缩小单次批量文件数量
- **资源未重命名**：将 `rename_assets_flag` 设为 `True`，并确认 ZIP 内存在 `figure`/`images` 等资源文件夹
