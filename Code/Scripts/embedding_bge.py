import os
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
CODE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = CODE_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(CODE_DIR / ".env", override=False)

if os.getenv("HF_OFFLINE", "1").lower() in {"1", "true", "yes", "on"}:
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")


def project_path_from_env(name: str, default: Path) -> Path:
    raw_value = os.getenv(name)
    path = Path(raw_value).expanduser() if raw_value else default
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from tqdm import tqdm

DATA_PATH = project_path_from_env("LEGAL_DATA_PATH", PROJECT_ROOT / "Data")
DB_SAVE_PATH = project_path_from_env("CHROMA_DB_PATH", PROJECT_ROOT / "Model" / "chroma_db")

def run_embedding():
    # 如果已存在旧库且你想彻底更新，取消下面这行的注释
    # if os.path.exists(DB_SAVE_PATH): shutil.rmtree(DB_SAVE_PATH)

    documents = []
    print(f"1. 启动全维度扫描：正在索引 {DATA_PATH} 下的 2024-2026 最新法律库...")

    if not DATA_PATH.exists():
        raise FileNotFoundError(f"法律原文目录不存在：{DATA_PATH}。请设置 LEGAL_DATA_PATH 或创建 Data 目录。")
    
    for root, dirs, files in os.walk(DATA_PATH):
        # 排除无文件的目录
        if not files: continue
        
        # 计算相对路径，例如 "2025至今新法条\司法解释"
        rel_path = os.path.relpath(root, DATA_PATH)
        
        for filename in files:
            if filename.endswith(".txt"):
                file_path = os.path.join(root, filename)
                try:
                    # 优先 utf-8，失败则 gbk
                    loader = TextLoader(file_path, encoding='utf-8')
                    docs = loader.load()
                except UnicodeDecodeError:
                    loader = TextLoader(file_path, encoding='gbk')
                    docs = loader.load()
                except Exception as e:
                    print(f"跳过损坏文件 {filename}: {e}")
                    continue

                for d in docs:
                    d.metadata["source"] = filename
                    d.metadata["category_path"] = rel_path # 注入路径信息
                documents.extend(docs)
                
    print(f"成功加载 {len(documents)} 份法律/案例原始文书。")
    if not documents:
        raise ValueError(f"未在 {DATA_PATH} 下找到 .txt 法律文档。")

    print("2. 执行语义切块 (Chunk Size: 800)...")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=150)
    split_docs = text_splitter.split_documents(documents)
    print(f"切块完成，共生成 {len(split_docs)} 个逻辑片段。")

    print("3. 初始化 BGE-M3 嵌入模型...")
    embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-m3")

    print("4. 构建持久化 ChromaDB (V2)...")
    DB_SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    vectordb = Chroma(persist_directory=str(DB_SAVE_PATH), embedding_function=embeddings)
    
    batch_size = 100 
    for i in tqdm(range(0, len(split_docs), batch_size), desc="向量化进度"):
        batch_docs = split_docs[i : i + batch_size]
        vectordb.add_documents(documents=batch_docs)
        
    print(f"\n🎉 升级完毕！2025-2026 法律知识库已就绪，存储于: {DB_SAVE_PATH}")

if __name__ == "__main__":
    run_embedding()
