# HuXin 护薪法律平台

HuXin 是一个面向农民工欠薪维权场景的法律智能平台。当前项目包含 FastAPI 后端、单页前端、DeepSeek 对话接口、Chroma 本地法律知识库检索、文件解析、RapidOCR 图片证据提取与 DOCX 文书导出能力。

## 项目结构

```text
Code/
  dual_api_server.py        # FastAPI 后端与静态前端托管
  Web/index.html            # 本地运行使用的前端页面
  Scripts/embedding_bge.py  # 从 Data 文本库重建 Chroma 向量库
Model/chroma_db/            # 当前可运行的 Chroma 向量库
Log/                        # 本地运行时聊天日志，不提交到 Git
```

## 本地运行

HuXin 现在只保留两个启动脚本：Mac 用 `run_local.sh`，Windows 用 `run_local.bat`。它们只负责启动本机后端，不再启动 cpolar / Cloudflare 隧道。

1. 第一次运行前准备环境变量：

```bash
cp .env.example Code/.env
```

把 `Code/.env` 里的 `DEEPSEEK_API_KEY` 改成你的真实密钥。现有本机 `Code/.env` 已被 `.gitignore` 保护，不会上传。

2. Mac 启动后端：

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

3. 后端日志出现 `Uvicorn running on http://127.0.0.1:8000` 后，打开：

```text
https://timemachinedmc.github.io/HuXin/
```

GitHub Pages 前端会默认连接你本机的 `http://127.0.0.1:8000`。健康检查地址是 `http://127.0.0.1:8000/api/health`。

启动脚本会把 `Model/chroma_db` 复制到 `.runtime/chroma_db` 后再加载，避免 Chroma 运行时写入污染 Git 里保存的知识库快照。需要刷新运行库时，删除 `.runtime/chroma_db` 后重新启动即可。

## 登录账号

农民工端：

```text
133 3107 4710
```

管理员看板：

```text
188 1193 9453
```

验证码保持为：

```text
8888
```

## 重建法律知识库

默认会直接使用已提交的 `Model/chroma_db`。如果要从原始 `.txt` 法律文本重建，把文本放入 `Data/`，然后运行：

```bash
source .venv/bin/activate
python Code/Scripts/embedding_bge.py
```

如需第一次下载 `BAAI/bge-m3`，将 `.env` 中 `HF_OFFLINE=0`。
