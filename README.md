# HuXin 护薪法律平台

HuXin 是一个面向农民工欠薪维权场景的法律智能平台。当前项目包含 FastAPI 后端、单页前端、DeepSeek 对话接口、Chroma 本地法律知识库检索、文件解析与 OCR 证据提取能力。

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

1. 准备环境变量：

```bash
cp .env.example Code/.env
```

把 `Code/.env` 里的 `DEEPSEEK_API_KEY` 改成你的真实密钥。现有本机 `Code/.env` 已被 `.gitignore` 保护，不会上传。

2. 一键启动：

```bash
./run_local.sh
```

启动后访问 `http://127.0.0.1:8000`。健康检查地址是 `http://127.0.0.1:8000/api/health`。

启动脚本会把 `Model/chroma_db` 复制到 `.runtime/chroma_db` 后再加载，避免 Chroma 运行时写入污染 Git 里保存的知识库快照。需要刷新运行库时，删除 `.runtime/chroma_db` 后重新启动即可。

Windows 可以运行：

```bat
run_local.bat
```

## GitHub Pages 与 cpolar

GitHub Pages 继续使用仓库根目录的 `index.html`。页面里的 `PAGE_API_BASE_URL` 保留为 cpolar 后端地址；本地由 FastAPI 打开 `Code/Web/index.html` 时，会自动使用当前本地服务地址。

cpolar 地址变化时，更新根目录 `index.html` 与 `Code/Web/index.html` 中的 `PAGE_API_BASE_URL` 即可。

也可以不改代码，直接用 `api` 参数临时指定新地址：

```text
https://timemachinedmc.github.io/HuXin/?api=https://你的新地址.r6.cpolar.top
```

页面会把这个地址保存到当前浏览器的 `localStorage`。如果要清除临时地址，在浏览器控制台运行：

```js
localStorage.removeItem("HUXIN_API_BASE_URL")
```

只在自己电脑本地调试时，直接访问 `http://127.0.0.1:8000` 最稳；打开 GitHub Pages 时，浏览器会走 cpolar 公开地址，不会自动连接你的本机后端。

## 重建法律知识库

默认会直接使用已提交的 `Model/chroma_db`。如果要从原始 `.txt` 法律文本重建，把文本放入 `Data/`，然后运行：

```bash
source .venv/bin/activate
python Code/Scripts/embedding_bge.py
```

如需第一次下载 `BAAI/bge-m3`，将 `.env` 中 `HF_OFFLINE=0`。
