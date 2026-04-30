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

HuXin 现在只保留两个后端启动脚本：Mac 用 `run_local.sh`，Windows 用 `run_local.bat`。它们只负责把本机后端启动在 `http://127.0.0.1:8000`。

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

3. 后端日志出现 `Uvicorn running on http://127.0.0.1:8000` 后，本机测试可以打开：

```text
https://timemachinedmc.github.io/HuXin/?api=http://127.0.0.1:8000
```

健康检查地址是 `http://127.0.0.1:8000/api/health`。

启动脚本会把 `Model/chroma_db` 复制到 `.runtime/chroma_db` 后再加载，避免 Chroma 运行时写入污染 Git 里保存的知识库快照。需要刷新运行库时，删除 `.runtime/chroma_db` 后重新启动即可。

## GitHub Pages 与 cpolar

GitHub Pages 只是静态前端，不能直接运行 Python 后端。iPhone、Win11 或任何不在后端本机上的设备打开 Pages 时，必须通过公网 HTTPS 后端访问，也就是 cpolar 这一类隧道。

当前前端默认公网后端写在 `index.html` 和 `Code/Web/index.html` 顶部脚本区：

```js
const PAGE_API_BASE_URL = "https://7de19a52.r39.cpolar.top";
```

以后 cpolar 重新分配域名时，只需要把上面这一行改成新的 `https://...cpolar.top`，提交并推送到 GitHub。也可以不改文件，临时用 URL 参数覆盖：

```text
https://timemachinedmc.github.io/HuXin/?api=https://新的地址.cpolar.top
```

cpolar 隧道必须指向运行后端的同一台电脑上的 `http://localhost:8000` 或 `http://127.0.0.1:8000`。如果公网地址打开后提示 `Tunnel unavailable`，通常表示 cpolar 客户端没有运行、隧道不在这台电脑上，或没有映射到 8000 端口；这时本机 `http://127.0.0.1:8000/api/health` 可能仍然是正常的。

为了方便调试，Pages 会先尝试 cpolar；如果你是在后端本机打开 Pages 且 cpolar 暂不可用，前端会自动回退到 `http://127.0.0.1:8000`。其他设备没有这个本机后端，所以仍然需要 cpolar 正常在线。

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
