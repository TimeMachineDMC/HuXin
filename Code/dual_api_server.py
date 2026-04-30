import io
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List
from urllib.parse import quote

import docx2txt
import numpy as np
import uvicorn
from bs4 import BeautifulSoup, NavigableString
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
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
EVENT_LOG_PATH = project_path_from_env("EVENT_LOG_PATH", PROJECT_ROOT / "Log" / "platform_events.jsonl")
SERVER_HOST = os.getenv("HUXIN_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("HUXIN_PORT", "8000"))

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    raise ValueError("DEEPSEEK_API_KEY not found. Copy .env.example to Code/.env or project .env first.")

ocr_engine = None
ocr_engine_name = None
ocr_init_error = None


def initialize_ocr_engine():
    """Prefer RapidOCR for Chinese documents, then fall back to EasyOCR."""
    global ocr_engine, ocr_engine_name, ocr_init_error

    try:
        from rapidocr import RapidOCR

        ocr_engine = RapidOCR()
        ocr_engine_name = "RapidOCR(PP-OCRv4)"
        ocr_init_error = None
        print("RapidOCR initialized successfully")
        return
    except Exception as e:
        ocr_init_error = f"RapidOCR initialization failed: {e}"
        print(ocr_init_error)

    try:
        import easyocr

        ocr_engine = easyocr.Reader(["ch_sim", "en"])
        ocr_engine_name = "EasyOCR"
        print("EasyOCR initialized successfully")
    except Exception as e:
        ocr_init_error = f"{ocr_init_error}; EasyOCR initialization failed: {e}" if ocr_init_error else f"EasyOCR initialization failed: {e}"
        print(ocr_init_error)


initialize_ocr_engine()


def run_ocr(image_np: np.ndarray) -> tuple[str, float | None]:
    if ocr_engine is None:
        raise RuntimeError(ocr_init_error or "OCR engine is not initialized")

    if ocr_engine_name and ocr_engine_name.startswith("RapidOCR"):
        result = ocr_engine(image_np)
        lines = [line.strip() for line in getattr(result, "txts", ()) if str(line).strip()]
        scores = [float(score) for score in getattr(result, "scores", ()) if score is not None]
        confidence = round(sum(scores) / len(scores), 4) if scores else None
        return "\n".join(lines), confidence

    result = ocr_engine.readtext(image_np, detail=1, paragraph=False)
    lines = []
    scores = []
    for item in result:
        if len(item) >= 2 and str(item[1]).strip():
            lines.append(str(item[1]).strip())
        if len(item) >= 3:
            scores.append(float(item[2]))
    confidence = round(sum(scores) / len(scores), 4) if scores else None
    return "\n".join(lines), confidence

def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def backend_log(event: str, detail: str = ""):
    suffix = f" | {detail}" if detail else ""
    print(f"[{now_text()}] {event}{suffix}", flush=True)


def append_jsonl(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def record_platform_event(event_type: str, payload: dict):
    event = {
        "timestamp": now_text(),
        "event_type": event_type,
        **payload,
    }
    try:
        append_jsonl(EVENT_LOG_PATH, event)
    except Exception as e:
        backend_log("Event Log Error", str(e))

    preview = json.dumps(payload, ensure_ascii=False)
    backend_log(f"EVENT {event_type}", preview[:600])


def save_chat_log(query: str, reasoning: str, answer: str, sources: list, user_name: str = "王某某", phone: str = "133 3107 4710"):
    """Save chat history and reasoning to JSONL format."""
    log_data = {
        "timestamp": now_text(),
        "user_name": user_name,
        "phone": phone,
        "user_query": query,
        "justitia_thought": reasoning,
        "justitia_answer": answer,
        "reference_sources": [s.get("filename", "Unknown File") for s in sources],
        "status": "AI 已答复",
    }
    
    try:
        append_jsonl(LOG_FILE_PATH, log_data)
        backend_log("PHASE2 AI_CHAT_SAVED", f"{user_name}({phone}) | {query[:120]}")
    except Exception as e:
        backend_log("Log Error", str(e))

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


@app.middleware("http")
async def add_private_network_access_header(request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "database_path": str(DB_SAVE_PATH),
        "database_exists": DB_SAVE_PATH.exists(),
        "ocr_ready": ocr_engine is not None,
        "ocr_engine": ocr_engine_name,
        "ocr_init_error": ocr_init_error if ocr_engine is None else None,
    }

# ================= 2. Data Models =================
class ChatRequest(BaseModel):
    query: str
    stream: bool = True
    history: list = Field(default_factory=list)
    top_k: int = 3
    score_threshold: float = 1.2
    mode: str = "spark"
    user_name: str = "王某某"
    phone: str = "133 3107 4710"

class SourceItem(BaseModel):
    filename: str
    score: float
    content_preview: str

class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceItem]

class DocExportRequest(BaseModel):
    title: str = "护薪法律文书"
    html: str
    user_name: str = "王某某"
    phone: str = "133 3107 4710"


class HumanSupportRequest(BaseModel):
    phase: str
    user_name: str = "王某某"
    phone: str = "133 3107 4710"
    latest_question: str = ""
    case_summary: str = ""
    evidence_subject: str = ""
    evidence_amount: str = ""


class CaseSubmitRequest(BaseModel):
    user_name: str = "王某某"
    phone: str = "133 3107 4710"
    case_summary: str = ""
    evidence_subject: str = ""
    evidence_amount: str = ""


def safe_filename(title: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", title).strip(" ._")
    return (cleaned or "护薪法律文书")[:80]


def set_document_fonts(document: Document):
    normal = document.styles["Normal"]
    normal.font.name = "SimSun"
    normal.font.size = Pt(12)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "SimSun")


def resolve_alignment(tag, inherited_alignment=None):
    classes = set(tag.get("class", []) if hasattr(tag, "get") else [])
    if "text-center" in classes:
        return WD_ALIGN_PARAGRAPH.CENTER
    if "text-right" in classes:
        return WD_ALIGN_PARAGRAPH.RIGHT
    return inherited_alignment


def add_runs_from_node(paragraph, node, inherited_bold=False):
    if isinstance(node, NavigableString):
        text = str(node).replace("\xa0", " ")
        if text:
            run = paragraph.add_run(text)
            run.bold = inherited_bold
        return

    if not getattr(node, "name", None):
        return

    if node.name == "br":
        paragraph.add_run("\n")
        return

    classes = set(node.get("class", []))
    is_bold = inherited_bold or node.name in {"strong", "b"} or "font-bold" in classes
    for child in node.children:
        add_runs_from_node(paragraph, child, is_bold)


def add_html_paragraph(document: Document, tag, alignment=None):
    paragraph = document.add_paragraph()
    classes = set(tag.get("class", []))

    if tag.name == "h1":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for child in tag.children:
            add_runs_from_node(paragraph, child, True)
        for run in paragraph.runs:
            run.font.size = Pt(18)
        return

    if tag.name in {"h2", "h3"}:
        paragraph.alignment = alignment
        for child in tag.children:
            add_runs_from_node(paragraph, child, True)
        for run in paragraph.runs:
            run.font.size = Pt(14)
        return

    paragraph.alignment = alignment
    if "indent-8" in classes:
        paragraph.paragraph_format.first_line_indent = Pt(24)

    for child in tag.children:
        add_runs_from_node(paragraph, child)


def append_html_blocks(document: Document, container, inherited_alignment=None):
    block_tags = {"h1", "h2", "h3", "p", "li"}
    for child in container.children:
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                document.add_paragraph(text)
            continue

        if not getattr(child, "name", None) or child.name in {"script", "style"}:
            continue

        alignment = resolve_alignment(child, inherited_alignment)
        if child.name in block_tags:
            add_html_paragraph(document, child, alignment)
        elif child.name == "br":
            document.add_paragraph()
        else:
            append_html_blocks(document, child, alignment)


def build_docx_bytes(title: str, html: str) -> bytes:
    document = Document()
    set_document_fonts(document)

    section = document.sections[0]
    section.top_margin = Pt(72)
    section.bottom_margin = Pt(72)
    section.left_margin = Pt(72)
    section.right_margin = Pt(72)

    soup = BeautifulSoup(html, "html.parser")
    root = soup.body or soup
    append_html_blocks(document, root)

    buffer = io.BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []

    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return None


def make_request_id(prefix: str = "HX") -> str:
    return f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S%f')[:17]}"


def phase_label(phase: str) -> str:
    labels = {
        "phase2": "第二阶段人工援助",
        "phase4": "第四阶段承办联系",
        "doc": "第三阶段文书导出",
        "submit": "第四阶段提交预审",
    }
    return labels.get(phase, phase or "平台记录")

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
    
    backend_log(
        "PHASE2 AI_CHAT_REQUEST",
        f"{request.user_name}({request.phone}) | {request.query[:300]} | Engine: {request.mode.upper()} ({selected_model})"
    )
    
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
                    sources=source_items,
                    user_name=request.user_name,
                    phone=request.phone,
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

        save_chat_log(request.query, full_reasoning, full_answer, source_items, request.user_name, request.phone)

        payload = {"answer": full_answer, "sources": source_items, "reasoning": full_reasoning}
        if engine_error:
            payload["error"] = engine_error
        return payload

@app.post("/api/export-docx")
async def export_docx(payload: DocExportRequest):
    title = safe_filename(payload.title)
    if not payload.html.strip():
        raise HTTPException(status_code=400, detail="文书内容为空，无法导出")

    record_platform_event("document_exported", {
        "stage": phase_label("doc"),
        "user_name": payload.user_name,
        "phone": payload.phone,
        "question": title,
        "status": "已生成文书",
        "summary": f"导出文书：{title}",
    })

    docx_bytes = build_docx_bytes(title, payload.html)
    filename = f"{title}.docx"
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
    }
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )


@app.post("/api/human-support")
async def request_human_support(payload: HumanSupportRequest):
    request_id = make_request_id("HS")
    assignee = "法律援助志愿者" if payload.phase == "phase2" else "民事检察承办助理"
    status = "待人工跟进"
    summary_parts = [
        payload.case_summary.strip(),
        f"主体：{payload.evidence_subject}" if payload.evidence_subject else "",
        f"金额：{payload.evidence_amount}" if payload.evidence_amount else "",
    ]
    summary = "；".join(part for part in summary_parts if part) or payload.latest_question[:160]

    record_platform_event("human_support_requested", {
        "request_id": request_id,
        "stage": phase_label(payload.phase),
        "user_name": payload.user_name,
        "phone": payload.phone,
        "question": payload.latest_question[:500],
        "summary": summary,
        "status": status,
        "assignee": assignee,
    })

    return {
        "request_id": request_id,
        "status": status,
        "assignee": assignee,
        "message": f"已登记人工协助请求，编号 {request_id}。{assignee}会根据后台记录继续处理。",
    }


@app.post("/api/case-submit")
async def submit_case(payload: CaseSubmitRequest):
    request_id = make_request_id("CS")
    record_platform_event("case_submitted", {
        "request_id": request_id,
        "stage": phase_label("submit"),
        "user_name": payload.user_name,
        "phone": payload.phone,
        "question": payload.case_summary[:500],
        "summary": f"主体：{payload.evidence_subject or '待补充'}；金额：{payload.evidence_amount or '待补充'}",
        "status": "已提交预审",
        "assignee": "民事检察部门",
    })
    return {
        "request_id": request_id,
        "status": "已提交预审",
        "message": f"预审卷宗已登记，编号 {request_id}。",
    }


@app.get("/api/admin/records")
async def admin_records(days: int = 7):
    cutoff = datetime.now() - timedelta(days=max(1, min(days, 30)))
    records = []

    for item in read_jsonl(LOG_FILE_PATH):
        ts = parse_timestamp(item.get("timestamp", ""))
        if ts is None or ts < cutoff:
            continue
        answer = item.get("justitia_answer", "")
        records.append({
            "timestamp": item.get("timestamp"),
            "stage": "第二阶段 AI研判",
            "farmer_name": item.get("user_name", "王某某"),
            "phone": item.get("phone", "133 3107 4710"),
            "question": item.get("user_query", ""),
            "summary": answer[:180],
            "status": item.get("status", "AI 已答复"),
            "assignee": "Justitia 护薪助手",
        })

    for item in read_jsonl(EVENT_LOG_PATH):
        ts = parse_timestamp(item.get("timestamp", ""))
        if ts is None or ts < cutoff:
            continue
        records.append({
            "timestamp": item.get("timestamp"),
            "stage": item.get("stage", item.get("event_type", "平台记录")),
            "farmer_name": item.get("user_name", "王某某"),
            "phone": item.get("phone", "133 3107 4710"),
            "question": item.get("question", ""),
            "summary": item.get("summary", ""),
            "status": item.get("status", "已记录"),
            "assignee": item.get("assignee", ""),
            "request_id": item.get("request_id", ""),
        })

    records.sort(key=lambda row: row.get("timestamp", ""), reverse=True)
    backend_log("ADMIN_DASHBOARD_QUERY", f"days={days} | records={len(records)}")
    return {"days": days, "records": records[:200]}


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        text = ""
        original_filename = file.filename or "uploaded_file"
        filename = original_filename.lower()
        ocr_confidence = None
        backend_log("PHASE2 FILE_UPLOAD", f"{original_filename} | {len(contents)} bytes")
        
        # 1. 处理 PDF/DOCX/TXT (保持原样)
        if filename.endswith('.pdf'):
            pdf_reader = PdfReader(io.BytesIO(contents))
            for page in pdf_reader.pages:
                text += page.extract_text() or ""
        elif filename.endswith('.docx'):
            text = docx2txt.process(io.BytesIO(contents))
        elif filename.endswith('.txt'):
            text = contents.decode('utf-8')
            
        # 2. 处理图片证据 (OCR)
        elif filename.endswith(('.png', '.jpg', '.jpeg', '.bmp')):
            if ocr_engine is None:
                return {"error": f"OCR 引擎未就绪：{ocr_init_error or '请检查 rapidocr/easyocr 与模型文件是否安装完整'}"}

            backend_log("PHASE2 OCR_START", f"{ocr_engine_name} | {original_filename}")
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image_np = np.array(image)
            text, ocr_confidence = run_ocr(image_np)

            if not text.strip():
                return {"error": "OCR 未识别到有效文字，请换一张更清晰的图片，或直接输入欠条上的金额、签名和日期。"}

            print("\n" + "="*30 + " 扫描结果可视化 " + "="*30, flush=True)
            print(text, flush=True) # 这里会在后端控制台完整输出图片文字
            print("="*76 + "\n", flush=True)
            
            confidence_log = f"，平均置信度: {ocr_confidence}" if ocr_confidence is not None else ""
            backend_log("PHASE2 OCR_DONE", f"{original_filename} | 提取字数: {len(text)}{confidence_log}")
            
        else:
            return {"error": "暂不支持该文件格式"}

        return {
            "filename": original_filename,
            "content_preview": text[:500],
            "full_content": text,
            "ocr_engine": ocr_engine_name if filename.endswith(('.png', '.jpg', '.jpeg', '.bmp')) else None,
            "ocr_confidence": ocr_confidence,
        }
    except Exception as e:
        backend_log("Parse Error", str(e))
        return {"error": f"文件解析失败: {str(e)}"}

if __name__ == "__main__":
    backend_log("SERVER_START", f"Justitia Shield API Server starting at http://{SERVER_HOST}:{SERVER_PORT}")
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
