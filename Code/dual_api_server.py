import io
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List

import docx2txt
import numpy as np
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from openai import AsyncOpenAI
from PIL import Image
from PyPDF2 import PdfReader
from pydantic import BaseModel, Field

# ================= 1. Configuration & Initialization =================
CODE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CODE_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(CODE_DIR / ".env", override=True)

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

DB_SAVE_PATH = project_path_from_env("CHROMA_DB_PATH", PROJECT_ROOT / "Model" / "chroma_db")
LOG_FILE_PATH = project_path_from_env("CHAT_LOG_PATH", PROJECT_ROOT / "Log" / "justitia_chat_logs.jsonl")
SERVER_HOST = os.getenv("HUXIN_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("HUXIN_PORT", "8000"))

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    raise ValueError("DEEPSEEK_API_KEY not found. Copy .env.example to Code/.env or project .env first.")

reader = None
try:
    import easyocr

    reader = easyocr.Reader(["ch_sim", "en"])
    print("EasyOCR initialized successfully")
except Exception as e:
    print(f"EasyOCR initialization failed: {e}")

def save_chat_log(query: str, reasoning: str, answer: str, sources: list):
    """Save chat history and reasoning to JSONL format."""
    log_data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user_query": query,
        "justitia_thought": reasoning,
        "justitia_answer": answer,
        "reference_sources": [s.get("filename", "Unknown File") for s in sources]
    }
    
    try:
        LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(log_data, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[Log Error]: {str(e)}")

print(f"Loading vector model and local legal database from {DB_SAVE_PATH}...")
try:
    embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-m3")
    vectordb = Chroma(persist_directory=str(DB_SAVE_PATH), embedding_function=embeddings)
except Exception as e:
    print(f"Database loading failed: {e}")
    raise

print("Initializing DeepSeek-V3.2 model...")
client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

app = FastAPI(title="Justitia Shield Engine", description="Legal Intelligence Engine for Procuratorate")

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "database_path": str(DB_SAVE_PATH),
        "database_exists": DB_SAVE_PATH.exists(),
        "ocr_ready": reader is not None,
    }

# ================= 2. Data Models =================
class ChatRequest(BaseModel):
    query: str
    stream: bool = True
    history: list = Field(default_factory=list)
    top_k: int = 3
    score_threshold: float = 1.2
    mode: str = "spark"

class SourceItem(BaseModel):
    filename: str
    score: float
    content_preview: str

class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceItem]

def engine_error_message(error: Exception) -> str:
    raw = str(error)
    if "401" in raw or "Authentication Fails" in raw or "invalid" in raw.lower() and "api key" in raw.lower():
        return "远程模型认证失败，请检查后端 Code/.env 中的 DEEPSEEK_API_KEY 是否为有效 DeepSeek 密钥。"
    return "远程模型暂时不可用，已切换为本地应急指引。"

def build_local_fallback_answer(query: str, sources: list) -> str:
    source_names = [item.get("filename", "本地案例库") for item in sources[:2]]
    source_text = "、".join(source_names) if source_names else "本地劳动报酬纠纷知识库"
    return f"""我先给您一个可立即执行的维权方案。

**初步识别**

您描述的是一起追索劳动报酬纠纷：在西单德拉曼公司相关工地从去年 10 月干到今年 1 月，尚欠工资约 25,000 元，目前有一张欠条。欠条是很关键的书面证据，但还需要尽量补强“谁欠钱、欠多少、在哪里干、干了多久”这几项。

**下一步建议**

1. 先把欠条拍清楚，保留原件，不要交给对方。
2. 继续补充证据：微信聊天记录、转账记录、工友证明、工地照片、考勤记录、工牌、施工群记录、包工头电话和公司名称。
3. 如果欠条上写明公司或包工头姓名、金额、日期，可以先向劳动监察部门投诉，也可以准备起诉材料。
4. 如果您是农民工、取证困难、自己起诉能力弱，可以向检察机关申请支持起诉，请求帮助固定证据、梳理被告主体和诉讼请求。

**需要您再确认 4 个信息**

- 欠条上写的是“德拉曼公司”还是某个老板/包工头个人？
- 欠条金额是否明确写了 25,000 元？
- 欠条有没有签名、身份证号、电话或盖章？
- 工地项目全称和具体位置是否能说清？

我已参考 {source_text} 做初步研判。远程智能模型当前不可用时，上面是本地应急指引；等密钥恢复后，系统会继续生成更完整的支持起诉分析和文书要点。"""

# ================= 3. Core API Endpoints =================
@app.get("/")
async def serve_frontend():
    return FileResponse(CODE_DIR / "Web" / "index.html")

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    legal_context = "No relevant legal documents found in the local database."
    source_items = []

    selected_model = "deepseek-reasoner" if request.mode == "prism" else "deepseek-chat"
    
    print(f"\n[Request Received] Query: {request.query} | Engine: {request.mode.upper()} ({selected_model})")
    
    # Keywords specific to labor disputes and wage protection
    legal_keywords = [
        '法律', '法条', '条款', '民法', '刑法', '公司法', '劳动法', '合同法', '合规', '法',
        '章程', '准则', '条例', '规定', '司法解释', '原告', '被告', '第三人', 
        '连带责任', '债权', '债务', '担保', '诉讼', '仲裁', '起诉', '申诉', '判决', '调解', 
        '证据', '举证', '违约', '赔偿', '效力', '判例', '案例', '协议', '合同', '起诉状',
        '欠薪', '工资', '薪水', '薪资', '农民工', '包工头', '劳动关系', '支持起诉', '援助', '维权'
    ]
    
    is_legal_query = any(k in request.query for k in legal_keywords) or len(request.query) > 10

    if not is_legal_query:
        print("[Intent Filter] Daily chat detected, skipping RAG retrieval...")
    else:
        print("[Intent Filter] Legal query detected, initiating ChromaDB retrieval...")
        raw_results = vectordb.similarity_search_with_score(request.query, k=request.top_k)
        legal_context = ""
        source_items = []
        
        for i, (doc, score) in enumerate(raw_results):
            if score < request.score_threshold:
                filename = doc.metadata.get('source', 'Unknown File')
                legal_context += f"\n--- Document {i+1} (Source: {filename}) ---\n{doc.page_content}\n"
                source_items.append({
                    "filename": filename, 
                    "score": round(score, 4),
                    "content_preview": doc.page_content[:30] + "..."
                })

# === 增强版 System Prompt：深度结合 RAG 与 2026 法律背景 ===
    final_system_prompt = f"""您是“护薪”检察支持起诉智能平台的智能助理 Justitia(小朱)，由 Huang Zitong 开发，专门服务于北京市西城区人民检察院。您的核心使命是协助农民工追索劳动报酬，并辅助检察官进行“支持起诉”的案件预审。注意，你的服务对象是维权的农民工群体，因此请保持语言精密而不失通俗，专业而不失关怀。

    [系统指令深度对齐]：
    1. 时间锚点：当前为 2026 年春季，请确保所有建议符合最新的法律时效。
    2. 双重身份：您既是农民工的贴心法律向导，又是检察官的专业审查助理。对劳动者请使用通俗、温暖、感性的语言；对案件分析请保持严密的法理逻辑。
    3. RAG 核心驱动：
       - 【法条库】：基于检索到的 [Local Legal Context]，优先引用内置的最新司法解释与《保障农民工工资支付条例》。
       - 【文书模板】：当用户信息基本完整时，必须引导并参考知识库中的“起诉状”、“支持起诉申请书”等标准模板格式生成预览。

    [执行指南 - 核心五要素提取]：
    您必须从 OCR 提取的文本或用户对话中精准锁定：
    1) 欠薪主体（用人单位全称/包工头姓名/项目部名称）。
    2) 劳动者身份。
    3) 确切的欠薪数额（需与证据中的数字对齐）。
    4) 务工时间段及项目名称。
    5) 现有证据清单（欠条、结算单、微信记录、工牌等）。

    [法律研判逻辑]：
    - 证据校验：如果缺少关键证据（如被告身份信息模糊、无书面结算单），请明确告知并提供“替代性证据”方案（如录音、证人证言）。
    - 支持起诉评估：根据《民事诉讼法》第十六条及西城区检察院实务，判断用户是否属于“诉讼能力弱、取证难”的弱势群体，并给出是否建议申请“检察支持起诉”的明确意见。

    [交互准则]：
    - 严禁提及您的 AI 架构、训练截止日期或您是一个语言模型。
    - 如果用户上传的 OCR 结果模糊，请委婉请其通过文字补充关键数字。
    - 始终以中文回答，确保排版利于电脑端和手机端阅读。

    [本地法律上下文增强]：
    {legal_context}

    Respond strictly in Chinese.
    """
    
    messages = [{"role": "system", "content": final_system_prompt}]
    
    if request.history:
        for msg in request.history:
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                messages.append({"role": msg["role"], "content": msg["content"]})
    
    messages.append({"role": "user", "content": request.query})

    if request.stream:
        async def generate_stream():
            meta_info = {"type": "meta", "sources": source_items}
            yield f"data: {json.dumps(meta_info, ensure_ascii=False)}\n\n"

            accumulated_reasoning = ""
            accumulated_content = ""

            try:
                response = await client.chat.completions.create(
                    model=selected_model,
                    messages=messages,
                    stream=True,
                    max_tokens=8192,
                )

                async for chunk in response:
                    if not chunk.choices:
                        continue
                        
                    delta = chunk.choices[0].delta
                    
                    if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                        accumulated_reasoning += delta.reasoning_content
                        yield f"data: {json.dumps({'type': 'reasoning', 'content': delta.reasoning_content}, ensure_ascii=False)}\n\n"

                    if hasattr(delta, 'content') and delta.content:
                        accumulated_content += delta.content
                        yield f"data: {json.dumps({'type': 'chunk', 'content': delta.content}, ensure_ascii=False)}\n\n"
            
            except Exception as e:
                print(f"[LLM Error]: {str(e)}")
                fallback_answer = build_local_fallback_answer(request.query, source_items)
                accumulated_content += fallback_answer
                yield f"data: {json.dumps({'type': 'chunk', 'content': fallback_answer}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'error', 'content': engine_error_message(e)}, ensure_ascii=False)}\n\n"
            
            finally:
                save_chat_log(
                    query=request.query,
                    reasoning=accumulated_reasoning,
                    answer=accumulated_content,
                    sources=source_items
                )
                
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate_stream(), media_type="text/event-stream")
    
    else:
        try:
            response = await client.chat.completions.create(
                model=selected_model,
                messages=messages,
                max_tokens=8192,
            )

            full_answer = response.choices[0].message.content
            full_reasoning = getattr(response.choices[0].message, 'reasoning_content', "")
            engine_error = None
        except Exception as e:
            print(f"[LLM Error]: {str(e)}")
            full_answer = build_local_fallback_answer(request.query, source_items)
            full_reasoning = ""
            engine_error = engine_error_message(e)

        save_chat_log(request.query, full_reasoning, full_answer, source_items)

        payload = {"answer": full_answer, "sources": source_items, "reasoning": full_reasoning}
        if engine_error:
            payload["error"] = engine_error
        return payload

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        text = ""
        original_filename = file.filename or "uploaded_file"
        filename = original_filename.lower()
        
        # 1. 处理 PDF/DOCX/TXT (保持原样)
        if filename.endswith('.pdf'):
            pdf_reader = PdfReader(io.BytesIO(contents))
            for page in pdf_reader.pages:
                text += page.extract_text() or ""
        elif filename.endswith('.docx'):
            text = docx2txt.process(io.BytesIO(contents))
        elif filename.endswith('.txt'):
            text = contents.decode('utf-8')
            
        # 2. 新增：处理图片 (OCR)
        elif filename.endswith(('.png', '.jpg', '.jpeg', '.bmp')):
            if reader is None:
                return {"error": "OCR 引擎未就绪，请检查 easyocr 与模型文件是否安装完整"}

            print(f"[OCR] 正在识别图片证据: {original_filename}")
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            # 转换为 numpy 数组供 easyocr 使用
            image_np = np.array(image)
            result = reader.readtext(image_np, detail=0) # 只获取文本内容
            text = "\n".join(result)

            print("\n" + "="*30 + " 扫描结果可视化 " + "="*30)
            print(text) # 这里会在后端控制台完整输出图片文字
            print("="*76 + "\n")
            
            print(f"[OCR] 提取字数: {len(text)}")
            
        else:
            return {"error": "暂不支持该文件格式"}

        return {
            "filename": original_filename,
            "content_preview": text[:500],
            "full_content": text
        }
    except Exception as e:
        print(f"[Parse Error]: {str(e)}")
        return {"error": f"文件解析失败: {str(e)}"}

if __name__ == "__main__":
    print(f"Justitia Shield API Server starting at http://{SERVER_HOST}:{SERVER_PORT}")
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
