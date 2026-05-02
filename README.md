# HuXin “护薪”检查支持起诉智能平台

HuXin 是一个面向农民工欠薪维权场景的法律智能平台。当前项目包含 FastAPI 后端、前端、对话接口、Chroma 本地法律知识库检索、文件解析、RapidOCR 图片证据提取与 DOCX 文书导出能力。


## 项目结构

```text
Code/
  dual_api_server.py        # FastAPI 后端与静态前端托管
  Web/index.html            # 本地运行使用的前端页面
  Scripts/embedding_bge.py  # 从 Data 文本库重建 Chroma 向量库
Model/chroma_db/            # 当前可运行的 Chroma 向量库
Log/                        # 本地运行时聊天日志，不提交到 Git
```

## 快速开始

HuXin 使用后端启动脚本：Mac 用 `run_local.sh`，Windows 用 `run_local.bat`。它们只负责把本机后端启动在 `http://127.0.0.1:8000`。

1. 第一次运行前准备环境变量：

```bash
cp .env.example Code/.env
```

将 `Code/.env` 里的 `DEEPSEEK_API_KEY` 改成真实密钥。


2. 启动程序：

Mac 启动后端：

```bash
./run_local.sh
```

Windows 启动后端：

```bat
run_local.bat
```

如果后端已经在运行，脚本会直接显示实时后端日志。浏览器里发起 AI 研判、文书导出、提交预审、人工协助请求时，终端会同步打印记录。此时按 `Ctrl-C` 只是停止看日志，不会关闭后端。

关闭后端：

```bash
./run_local.sh stop
```

Windows：

```bat
run_local.bat stop
```

3. 后端日志出现 `Uvicorn running on http://127.0.0.1:8000` 后，本机测试可以打开：

```text
https://timemachinedmc.github.io/HuXin/?api=http://127.0.0.1:8000
```

健康检查地址是 `http://127.0.0.1:8000/api/health`。

启动脚本会把 `Model/chroma_db` 复制到 `.runtime/chroma_db` 后再加载，避免 Chroma 运行时写入污染 Git 里保存的知识库快照。需要刷新运行库时，删除 `.runtime/chroma_db` 后重新启动即可。


## 重建法律知识库

默认会直接使用已提交的 `Model/chroma_db`。如果要从原始 `.txt` 法律文本重建，把文本放入 `Data/`，然后运行：

```bash
source .venv/bin/activate
python Code/Scripts/embedding_bge.py
```

如需第一次下载 `BAAI/bge-m3`，置 `.env` 中 `HF_OFFLINE=0`。


## 更新日志

04/24/2026 初版完成上线

04/27/2026 接入DeepSeek-V4

04/28/2026 主 OCR 换成 RapidOCR(PP-OCRv4)，新增真实文件导出接口 /api/export-docx

04/30/2026 增加“管理员看板”，调整证据链状态逻辑链

05/01/2026 管理员看板新增“案件详情”面板，点击记录可看案情详细；聊天页证据链改为优先使用后端结构化结果，并新增案件时间线



## 开源协议
本项目采用 [MIT License](LICENSE) 许可协议。