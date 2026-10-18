"""
mineru_extractor.py
===================
Automates PDF parsing using MinerU's Precision Extract API (v4) with VLM model,
and processes extracted Markdown tables using the 4-Stage Hybrid Multimodal Cross-Referencing
Pipeline with Gemini API for 100% structured JSON fidelity.

Architecture:
  - Stage 0: MinerU Precision API v4 (Structural table & checkmark anchor)
  - Stage 1: Multimodal Visual Proofreader (PDF image + Raw Markdown cross-referenced via Files API)
  - Stage 2: Modular Technical Specifications & Standard Equipment Extractor (10 categories)
  - Stage 3: Modular Paintwork & Upholstery Matrix Extractor (2D color-upholstery relationship)
  - Stage 4: Pure Python JSON Assembler & Business Rules Injection (Zero API cost)
"""

import os
import sys
import time
import json
import re
import socket
import zipfile
import io
import requests
import html


sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
import pypdf
import difflib
import tempfile
import pypdfium2 as pdfium
from google import genai
from google.genai import types

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
except ImportError:
    pass

socket.setdefaulttimeout(120)

# ─── API Setup ────────────────────────────────────────────────────────────────
MINERU_API_TOKEN = os.environ.get("MINERU_API_TOKEN", "").strip()
PRECISION_BASE_URL = "https://mineru.net/api/v4"

if MINERU_API_TOKEN:
    print("[API] MinerU Precision API: Token loaded successfully.")
else:
    print("[API] ERROR: MINERU_API_TOKEN is not set. Please add it to your .env file.")
    sys.exit(1)

MINERU_HEADERS = {
    "Authorization": f"Bearer {MINERU_API_TOKEN}",
    "Content-Type": "application/json"
}

API_KEYS = []
for idx in range(1, 4):
    k = os.environ.get(f"GEMINI_API_KEY_{idx}", "").strip()
    if k:
        API_KEYS.append(k)
if not API_KEYS and os.environ.get("GEMINI_API_KEY"):
    API_KEYS.append(os.environ.get("GEMINI_API_KEY").strip())

if not API_KEYS:
    print("[API] ERROR: No Gemini API keys found in .env. Please set GEMINI_API_KEY_1..3.")
    sys.exit(1)

KEY_COUNTER = 0

def get_gemini_client():
    global KEY_COUNTER
    key = API_KEYS[KEY_COUNTER % len(API_KEYS)]
    KEY_COUNTER += 1
    return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=120000))


def generate_with_fallback(client, contents, config=None, is_json=False):
    models_to_try = ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash"]
    for m_name in models_to_try:
        for attempt in range(4):
            try:
                if config:
                    return client.models.generate_content(model=m_name, contents=contents, config=config)
                elif is_json:
                    return client.models.generate_content(
                        model=m_name, contents=contents,
                        config=types.GenerateContentConfig(response_mime_type="application/json")
                    )
                else:
                    return client.models.generate_content(model=m_name, contents=contents)
            except Exception as e:
                wait_s = (attempt + 1) * 3
                print(f"   -> Warning: {m_name} attempt {attempt+1} encountered: {e}. Retrying in {wait_s}s...")
                time.sleep(wait_s)
    raise RuntimeError("All models failed to generate content after retries.")


def robust_json_loads(text: str):
    if not text:
        return {}
    clean_text = text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    elif clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
    clean_text = clean_text.strip()
    try:
        return json.loads(clean_text)
    except Exception:
        # Sanitize invalid \uXXXX escape sequences (e.g. \u not followed by 4 hex digits)
        sanitized = re.sub(r'\\u(?![0-9a-fA-F]{4})', r'\\\\u', clean_text)
        return json.loads(sanitized)


# ─── PROMPTS ──────────────────────────────────────────────────────────────────

PROMPT_MULTIMODAL_PROOFREADER_TH = """คุณคือผู้เชี่ยวชาญด้านการตรวจทานเอกสารสเปกรถยนต์ BMW (Automotive Specification Proofreader)
คุณได้รับข้อมูล 2 ส่วนพร้อมกัน:
1. ไฟล์ PDF โบรชัวร์ต้นฉบับของ BMW (ใช้เป็น Visual Ground Truth ความถูกต้องสูงสุด)
2. รายชื่อหัวข้อสเปก, ชื่อหมวดหมู่, ค่าสเปกที่เป็นคำอธิบาย และชื่อสี/วัสดุเบาะ ที่สกัดมาได้จากระบบ OCR

เป้าหมายของคุณคือ:
นำรายชื่อข้อความไปเทียบกับ "ภาพจริงบนหน้า PDF" เพื่อตรวจทานและแก้ไขคำสะกดผิดให้ตรงกับตัวอักษรที่พิมพ์อยู่จริงบนเอกสาร PDF 100%:
- แก้ไขคำสะกดผิด, สระลอย, วรรณยุกต์เพี้ยน หรือพยัญชนะไทยที่ OCR อ่านผิดพลาด (เช่น "โพเบรก" -> "ไฟเบรก", "สปอยเลอร์หลังดีไชน์" -> "สปอยเลอร์หลังดีไซน์")
- ตรวจทานคำศัพท์ภาษาอังกฤษที่ปรากฏในวงเล็บหรือในตารางอย่างเข้มงวด และแก้ไขตัวอักษรที่ OCR อ่านผิดพลาด (เช่น "(Broke Assist)" -> "(Brake Assist)")
- ห้ามแทรกช่องว่างส่วนเกินคั่นกลางคำหรือกลุ่มคำภาษาไทยโดยไม่จำเป็น เช่น ให้คง "ระบบจำตำแหน่ง", "ระบบเปิด-ปิดบานประตู", "ระบบปรับการทำงาน", "เมื่อเกิดการชน" ไว้อย่างถูกต้องตามต้นฉบับ
- หากคำใดสะกดถูกต้องและตรงกับ PDF อยู่แล้ว ให้คงไว้ตามเดิม
- ตอบกลับในรูปแบบ STRICT JSON Object เท่านั้น โดยมีโครงสร้าง:
{
  "คำเดิมจาก OCR": "คำที่ถูกต้องตาม PDF"
}
ห้ามใส่คำอธิบายเพิ่มเติม นอกเหนือจาก JSON Object
"""

PROMPT_MULTIMODAL_PROOFREADER_EN = """You are an expert Automotive Technical Specification Proofreader for official BMW brochures.
You are provided with two inputs simultaneously:
1. The original BMW PDF Brochure (Use as the Visual Ground Truth of ultimate correctness).
2. A list of specification topic titles, category names, and paint/upholstery names extracted by OCR.

Your Sole Mission:
Cross-reference the provided text terms against the actual visual pages of the PDF.
Proofread and correct any character-level OCR misreadings, garbled words, broken characters, or font glitches so that the text perfectly matches what is printed in the PDF brochure (100% fidelity).
- If a term is already 100% correct, keep it as is.
- If a term has typos or OCR glitches, correct it to the exact text printed on the PDF.
- Return ONLY a STRICT JSON dictionary mapping each raw OCR term to its corrected term:
{
  "raw_ocr_term": "corrected_term"
}
Do NOT include any commentary, explanations, or text outside the JSON object.
"""

PROMPT_SPECS_TH = """You are an expert BMW Automotive Specification Analyst.
Your task is to take a pre-extracted and cleaned Markdown/HTML specification table from a BMW brochure and format the output into a strict JSON structure.

เป้าหมายของคุณคือ: ดึงข้อมูลสเปก "ทุกบรรทัด" และ "ทุกตัวอักษร" บนทุกหน้าของเอกสาร ห้ามตกหล่นแม้แต่ข้อเดียว

กฎเหล็กที่ต้องปฏิบัติตามอย่างเคร่งครัด:
1. ห้ามสรุปความ ห้ามย่อความ ห้ามตัดออปชันย่อยทิ้งเด็ดขาด ต้องดึงข้อมูลมาแบบคำต่อคำ (Verbatim) ให้ครบทุกบรรทัดที่ปรากฏในตาราง
2. ในเอกสารจะมีตารางอุปกรณ์มาตรฐาน (เช่น ระบบขับเคลื่อน อุปกรณ์ภายนอก อุปกรณ์ภายใน ความปลอดภัย ความบันเทิง) คุณต้องดึงข้อมูลเหล่านี้มาให้ครบถ้วน ห้ามข้ามเด็ดขาด
3. **การจัดการช่องว่าง (Blank Cells):**
   - หากช่องใดในตารางเป็นช่องว่างเปล่า หรือระบุเครื่องหมายขีด "-" ให้ระบุเป็น "-" เสมอ ห้ามคาดเดาหรือพยายามเติมสัญลักษณ์เองเด็ดขาด
   - หากช่องใดมีเครื่องหมาย ■ ให้ระบุเป็น "■" เสมอ
4. หมวดหมู่มาตรฐาน (10 หมวดหมู่หลัก):
   - "เครื่องยนต์และสมรรถนะ" (หรือ "มอเตอร์ไฟฟ้าและสมรรถนะ" สำหรับรถยนต์ไฟฟ้าล้วน EV)
   - "อัตราสิ้นเปลืองน้ํามันเชื้อเพลิง และระดับการปล่อย CO2"
   - "ล้อและยาง"
   - "มิติรถยนต์"
   - "ระบบขับเคลื่อนและเทคโนโลยี"
   - "อุปกรณ์ภายนอก"
   - "อุปกรณ์ภายใน"
   - "ระบบความบันเทิงและการสื่อสาร"
   - "ความปลอดภัย"
   - "ชุดตกแต่งพิเศษ"

JSON Output Structure:
{
  "series": "BMW <Series Name>",
  "models": [
    {
      "model_name": "<Model Name>",
      "specifications": [
        {
          "category": "<Category Name>",
          "details": [
            {
              "topic": "<Exact Topic Name>",
              "value": "<Value, ■, or ->"
            }
          ]
        }
      ]
    }
  ]
}
"""

PROMPT_SPECS_EN = """You are an expert BMW Automotive Specification Analyst.
Your task is to take a pre-extracted and cleaned Markdown/HTML specification table from a BMW brochure and format the output into a strict JSON structure.

Rules:
1. Verbatim extraction: Never summarize, shorten, or omit any rows or equipment options.
2. Standard Equipment: Extract all equipment rows under Exterior, Interior, Safety, Entertainment, etc.
3. Blank Cells: If empty or "-", output as "-". If marked with "■", output as "■".
4. Standard Categories (10 Core Categories):
   - "Engine and Performance" (or "Electric Motor and Performance" for BEV)
   - "Fuel Consumption and CO2 Emission"
   - "Wheels and Tyres"
   - "Dimension"
   - "Drivetrain and Technology"
   - "Exterior Equipment"
   - "Interior Equipment"
   - "Entertainment and Communication"
   - "Safety"
   - "Line / Package"

JSON Output Structure:
{
  "series": "BMW <Series Name>",
  "models": [
    {
      "model_name": "<Model Name>",
      "specifications": [
        {
          "category": "<Category Name>",
          "details": [
            {
              "topic": "<Exact Topic Name>",
              "value": "<Value, ■, or ->"
            }
          ]
        }
      ]
    }
  ]
}
"""

PROMPT_PAINT_TH = """You are an expert BMW Technical Specification Structuring Specialist.
Your task is to parse a cleaned BMW Paintwork & Upholstery Matrix table into JSON.

Rules:
1. Focus STRICTLY and ONLY on Paintwork & Upholstery combinations.
2. In the 2D matrix, rows are exterior paint colors, columns are upholstery materials and colors.
3. If an intersection cell contains "■", map it to "Upholstery Material - Color".
4. If an intersection cell is empty or "-", output "-".

CRITICAL CATEGORY REQUIREMENT: The category name for paintwork must strictly be "Paintwork / สีตัวถังและวัสดุภายใน".

JSON Output Structure:
{
  "series": "BMW <Series Name>",
  "models": [
    {
      "model_name": "<Model Name>",
      "specifications": [
        {
          "category": "Paintwork / สีตัวถังและวัสดุภายใน",
          "details": [
            {
              "topic": "<Paint Color Name>",
              "value": "<Upholstery Material - Color or ->"
            }
          ]
        }
      ]
    }
  ]
}
"""

PROMPT_PAINT_EN = """You are an expert BMW Technical Specification Structuring Specialist.
Your task is to parse a cleaned BMW Paintwork & Upholstery Matrix table into JSON.

Rules:
1. Focus STRICTLY and ONLY on Paintwork & Upholstery combinations.
2. In the 2D matrix, rows are exterior paint colors, columns are upholstery materials and colors.
3. If an intersection cell contains "■", map it to "Upholstery Material - Color".
4. If an intersection cell is empty or "-", output "-".

CRITICAL CATEGORY REQUIREMENT: The category name for paintwork must strictly be "Paintwork & Upholstery".

JSON Output Structure:
{
  "series": "BMW <Series Name>",
  "models": [
    {
      "model_name": "<Model Name>",
      "specifications": [
        {
          "category": "Paintwork & Upholstery",
          "details": [
            {
              "topic": "<Paint Color Name>",
              "value": "<Upholstery Material - Color or ->"
            }
          ]
        }
      ]
    }
  ]
}
"""

# ─── MINERU API CLIENT ────────────────────────────────────────────────────────

def _get_presigned_upload_url(file_name: str, max_retries: int = 5) -> tuple[str, str]:
    url = f"{PRECISION_BASE_URL}/file-urls/batch"
    payload = {
        "enable_formula": False,
        "language": "ch",       # 'ch' engine: best for mixed Thai/EN + complex table grids
        "enable_table": True,
        "vlm": True,            # Enable Vision Layout Model
        "model_version": "vlm", # Support both model configurations for maximum safety
        "table_flavor": "html", # Request HTML tables with rowspan/colspan support
        "files": [
            {
                "name": file_name,
                "is_ocr": True
            }
        ]
    }
    for attempt in range(max_retries):
        if attempt > 0:
            print(f"   [RETRY] Waiting 10s before retry {attempt+1}/{max_retries}...")
            time.sleep(10)
        try:
            resp = requests.post(url, json=payload, headers=MINERU_HEADERS, timeout=30)
            if resp.status_code == 429:
                print("   [WARN] 429 Too Many Requests on presign URL. Retrying...")
                time.sleep(30)
                continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") not in (0, 200, None):
                raise ValueError(f"API error: {data}")
            
            batch_id = data.get("data", {}).get("batch_id")
            file_urls = data.get("data", {}).get("file_urls", [])
            if not file_urls or not batch_id:
                raise ValueError(f"Missing file_urls or batch_id in response: {data}")
            
            upload_url = file_urls[0]
            if not upload_url:
                raise ValueError(f"Missing upload url in response: {data}")
                
            return upload_url, str(batch_id)
        except Exception as e:
            print(f"   [WARN] Presign URL request failed: {e}")
    raise ValueError(f"Failed to get presigned upload URL after {max_retries} attempts.")


def _upload_to_oss(upload_url: str, file_path: str, max_retries: int = 5) -> None:
    for attempt in range(max_retries):
        if attempt > 0:
            print(f"   [RETRY] Waiting 10s before OSS PUT retry {attempt+1}/{max_retries}...")
            time.sleep(10)
        try:
            print(f"   [UPLOAD] Uploading bytes to OSS...")
            with open(file_path, "rb") as f:
                resp = requests.put(upload_url, data=f, timeout=120)
            if resp.status_code in (200, 204):
                print("   [UPLOAD] OSS upload succeeded.")
                return
            print(f"   [WARN] OSS PUT returned HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"   [WARN] OSS PUT failed: {e}")
    raise ValueError("Failed to upload file to OSS after all retries.")


def _poll_precision_task(batch_id: str, timeout: int = 900) -> str:
    poll_url = f"{PRECISION_BASE_URL}/extract-results/batch/{batch_id}"
    start_time = time.time()
    poll_interval = 15

    print(f"   [POLL] Polling batch {batch_id} (timeout={timeout}s)...")
    while time.time() - start_time < timeout:
        time.sleep(poll_interval)
        elapsed = int(time.time() - start_time)
        try:
            resp = requests.get(poll_url, headers=MINERU_HEADERS, timeout=20)
            if resp.status_code == 429:
                print(f"      [{elapsed}s] WARN: 429 rate-limit on poll. Backing off 30s...")
                time.sleep(30)
                continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") not in (0, 200, None):
                print(f"      [{elapsed}s] WARN: Poll API returned code {data.get('code')}: {data.get('msg')}")
                continue
                
            results = data.get("data", {}).get("extract_result", [])
            if not results:
                print(f"      [{elapsed}s] WARN: Empty extract_result in response.")
                continue
                
            result_item = results[0]
            state = str(result_item.get("state") or result_item.get("status") or "").lower()
            print(f"      [{elapsed}s] Status: {state}")

            if state in ("success", "done"):
                md_url = result_item.get("md_url") or result_item.get("full_zip_url") or result_item.get("zip_url")
                if not md_url:
                    raise ValueError(f"Task completed successfully but no download URL found: {result_item}")

                print(f"      [SUCCESS] Completed in {elapsed}s. Downloading result from: {md_url[:80]}...")
                return _download_result(md_url)

            elif state in ("failed", "error"):
                err = result_item.get("err_msg") or result_item.get("message", "Unknown error occurred during processing.")
                raise ValueError(f"MinerU Precision task failed: {err}")

        except ValueError:
            raise
        except Exception as e:
            print(f"      [{elapsed}s] WARN: Poll error - {e}")

    raise TimeoutError(f"Precision batch task {batch_id} timed out after {timeout}s.")


def _download_result(url: str, max_retries: int = 5) -> str:
    for attempt in range(max_retries):
        if attempt > 0:
            print(f"   [RETRY] Waiting 10s before download retry {attempt+1}/{max_retries}...")
            time.sleep(10)
        try:
            resp = requests.get(url, timeout=60)
            if resp.status_code != 200:
                print(f"   [WARN] Download HTTP {resp.status_code}. Retrying...")
                continue

            content_type = resp.headers.get("Content-Type", "")
            if "zip" in content_type or url.endswith(".zip") or resp.content[:2] == b"PK":
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    md_files = [n for n in zf.namelist() if n.endswith(".md")]
                    if not md_files:
                        raise ValueError(f"No .md file found in result zip. Contents: {zf.namelist()}")
                    md_name = max(md_files, key=lambda n: zf.getinfo(n).file_size)
                    print(f"   [EXTRACT] Reading '{md_name}' from zip ({zf.getinfo(md_name).file_size} bytes)")
                    return zf.read(md_name).decode("utf-8")
            else:
                return resp.text
        except Exception as e:
            print(f"   [WARN] Download attempt failed: {e}")
    raise ValueError(f"Failed to download result from {url} after all retries.")


def parse_pdf_via_api(pdf_path: str, lang_code: str = "th") -> str:
    filename = os.path.basename(pdf_path)
    print(f"   [PRECISION] Starting Precision Extract for: {filename}")
    upload_url, batch_id = _get_presigned_upload_url(filename)
    _upload_to_oss(upload_url, pdf_path)
    return _poll_precision_task(batch_id)

# ─── 4-STAGE HYBRID MULTIMODAL PIPELINE FUNCTIONS ─────────────────────────────

def run_mineru_stage(pdf_path: str, lang_code: str = "th") -> str:
    raw_md_path = f"mineru_raw_{os.path.basename(pdf_path)}.md"
    if os.path.exists(raw_md_path):
        print(f"[MINERU] Found cached Raw Markdown: {raw_md_path}")
        with open(raw_md_path, "r", encoding="utf-8") as f:
            return f.read()

    print(f"\n[MINERU] Starting Precision Extract API (v4) for: {os.path.basename(pdf_path)}")
    try:
        md_content = parse_pdf_via_api(pdf_path, lang_code=lang_code)
        if not md_content or not md_content.strip():
            raise ValueError("MinerU returned empty content.")
            
        with open(raw_md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"[MINERU] Successfully extracted and cached to {raw_md_path}")
        return md_content
    except Exception as e:
        print(f"\n[FATAL ERROR] MinerU extraction failed for {os.path.basename(pdf_path)}: {e}")
        sys.exit(1)


PUA_MAP = {
    0xF705: '\u0e49', 0xF706: '\u0e49', 0xF707: '\u0e4a', 0xF708: '\u0e4b', 0xF709: '\u0e4c',
    0xF70A: '\u0e48', 0xF70B: '\u0e49', 0xF70C: '\u0e4a', 0xF70D: '\u0e4b', 0xF70E: '\u0e4c',
    0xF70F: '\u0e31', 0xF710: '\u0e31', 0xF711: '\u0e34', 0xF712: '\u0e35', 0xF713: '\u0e36',
    0xF714: '\u0e37', 0xF718: '\u0e3a', 0xF719: '\u0e38', 0xF71A: '\u0e39',
    0xFB00: 'ff', 0xFB01: 'fi', 0xFB02: 'fl', 0xFB03: 'ffi', 0xFB04: 'ffl',
}

def _normalize_pua(text: str) -> str:
    return ''.join(PUA_MAP.get(ord(ch), ch) for ch in text)

def _simplify_text(s: str) -> str:
    s = _normalize_pua(s)
    return re.sub(r'[^a-zA-Z\u0e01-\u0e2e]', '', s).lower()

def _text_similarity(a: str, b: str) -> float:
    sa, sb = _simplify_text(a), _simplify_text(b)
    if not sa or not sb:
        return 0.0
    if sa == sb:
        return 1.0
    if len(sa) >= 6 and len(sb) >= 6 and (sa in sb or sb in sa):
        return 0.95
    return difflib.SequenceMatcher(None, sa, sb).ratio()

def _is_fuzzy_substring(short_str: str, long_str: str, threshold: float = 0.60) -> bool:
    s_short = _simplify_text(short_str)
    s_long = _simplify_text(long_str)
    if not s_short or not s_long:
        return False
    if s_short in s_long:
        return True
    len_s = len(s_short)
    if len_s < 3:
        return False
    for start in range(len(s_long) - len_s + 1):
        window = s_long[start:start + len_s]
        if difflib.SequenceMatcher(None, s_short, window).ratio() >= threshold:
            return True
    return False

def pre_stage_1_table_harmonizer(raw_md: str, pdf_path: str, lang_code: str = "th") -> str:

    """
    [PRE-STAGE 1] Generic, model-agnostic Table Harmonizer:
    1. Pattern 1 (Dangling Text): Ingests plain-text lines stranded outside </table> back into table.
    2. Pattern 2 (Sequence Gap Recovery): Reconciles table rows against native PDF text stream to restore lines skipped by MinerU OCR.
    Saves intermediate artifact: pre_stage_1_harmonized_{pdf_basename}.md
    """
    pdf_basename = os.path.basename(pdf_path)
    harmonized_md_path = f"pre_stage_1_harmonized_{pdf_basename}.md"
    print(f"\n[PRE-STAGE 1] Starting Table Harmonizer ({pdf_basename})...")
    
    harmonized_md = raw_md
    
    # ─── PATTERN 1: Dangling Text Ingestion ────────────────────────────────────
    def ingest_dangling(match):
        table_content = match.group(1)
        dangling = match.group(2).strip()
        lines = [l.strip() for l in dangling.split('\n') if l.strip() and not l.strip().startswith(('#', '|', '<'))]
        if not lines:
            return match.group(0)
            
        all_rows = re.findall(r'<tr[^>]*>.*?</tr>', table_content, flags=re.DOTALL)
        num_cols = 2
        for r in all_rows:
            tds = re.findall(r'<td[^>]*>', r)
            if len(tds) > num_cols:
                num_cols = len(tds)
                
        injected_rows = []
        for line in lines:
            val_tds = ''.join(['<td>■</td>'] * (num_cols - 1))
            injected_rows.append(f"<tr><td>{line}</td>{val_tds}</tr>")
            print(f"   [HARMONIZER - Dangling Text] Ingested '{line}' into table ({num_cols} cols)")
            
        return f"<table>{table_content}{''.join(injected_rows)}</table>\n\n"

    p1 = re.compile(r'<table>(.*?<tr[^>]*>\s*<td\s+colspan=[\'"]?\d+[\'"]?[^>]*>[^<]+</td>\s*</tr>)\s*</table>\s*\n+([^<#\n][^<#]*?)\n+(?=(?:#+|<table>|\Z))', flags=re.DOTALL | re.IGNORECASE)
    harmonized_md = p1.sub(ingest_dangling, harmonized_md)
    
    # ─── PATTERN 2: Native PDF Stream Reconciliation ──────────────────────────
    try:
        reader = pypdf.PdfReader(pdf_path)
        all_pdf_lines = []
        for p_idx, page in enumerate(reader.pages):
            text = page.extract_text()
            if not text:
                continue
            raw_lines = [l.strip() for l in text.split('\n') if l.strip()]
            for l in raw_lines:
                norm_l = _normalize_pua(l)
                if norm_l.startswith('(') and all_pdf_lines and all_pdf_lines[-1][0] == p_idx + 1:
                    all_pdf_lines[-1] = (p_idx + 1, all_pdf_lines[-1][1] + " " + norm_l)
                else:
                    if len(_simplify_text(norm_l)) >= 3:
                        all_pdf_lines.append((p_idx + 1, norm_l))
                    
        table_matches = list(re.finditer(r'<table[^>]*>(.*?)</table>', harmonized_md, flags=re.DOTALL))
        for t_match in table_matches:
            t_content = t_match.group(1)
            # Gap recovery strictly applies to equipment tables with checkmarks (exclude Paintwork and Technical specs)
            if 'Paintwork' in t_content or 'สีตัวถัง' in t_content or not ('■' in t_content or '&#x25a0;' in t_content or '?' in t_content):
                continue
                
            full_rows = list(re.finditer(r'<tr[^>]*>.*?</tr>', t_content, flags=re.DOTALL))
            if not full_rows:
                continue

            # --- Pattern 2A: Trailing Empty Category Recovery ---
            last_row_html = full_rows[-1].group(0)
            cat_match = re.search(r'<td\s+colspan=[\'"]?\d+[\'"]?[^>]*>(.*?)</td>', last_row_html, flags=re.IGNORECASE)
            if cat_match:
                cat_name = re.sub(r'<[^>]+>', '', cat_match.group(1)).strip().replace('&#x27;', "'").replace('&quot;', '"').replace('&amp;', '&')
                num_cols = 2
                for r_m in full_rows[:-1]:
                    td_count = len(re.findall(r'<td[^>]*>', r_m.group(0)))
                    if td_count > num_cols:
                        num_cols = td_count
                
                cat_pdf_indices = [idx for idx, (p_num, pl) in enumerate(all_pdf_lines) if _text_similarity(pl, cat_name) >= 0.8]
                if cat_pdf_indices:
                    cat_idx = cat_pdf_indices[0]
                    cat_page = all_pdf_lines[cat_idx][0]
                    missing_options = []
                    for look_idx in range(cat_idx + 1, len(all_pdf_lines)):
                        p_num, pl = all_pdf_lines[look_idx]
                        if p_num != cat_page:
                            break
                        if any(stop_word in pl for stop_word in ['Paintwork', 'สีตัวถัง', 'BMW', 'Effective', 'Printed', 'พิมพ์วันที่', 'คู่มือ', 'Page', 'Z9']):
                            break
                        if len(_simplify_text(pl)) >= 3:
                            all_cell_texts = [_simplify_text(html.unescape(re.sub(r'<[^>]+>', '', c))) for c in re.findall(r'<td[^>]*>(.*?)</td>', harmonized_md, flags=re.DOTALL)]
                            if _simplify_text(pl) not in all_cell_texts:

                                missing_options.append(pl)
                    
                    if missing_options:
                        injected_rows = [f"<tr><td>{opt}</td>{''.join(['<td>■</td>'] * (num_cols - 1))}</tr>" for opt in missing_options]
                        row_matches = list(re.finditer(re.escape(last_row_html), harmonized_md))
                        if row_matches:
                            target_pos = row_matches[0].end()
                            harmonized_md = harmonized_md[:target_pos] + "\n" + "\n".join(injected_rows) + harmonized_md[target_pos:]
                            for opt in missing_options:
                                print(f"   [HARMONIZER - Trailing Category] Inserted '{opt}' under empty category '{cat_name}'")

            # --- Pattern 2B: In-Table Sequence Gap Recovery ---
            row_topics = []
            for r_m in full_rows:
                cells = re.findall(r'<td[^>]*>(.*?)</td>', r_m.group(0), flags=re.DOTALL)
                c0 = re.sub(r'<[^>]+>', '', cells[0]).strip().replace('&#x27;', "'").replace('&quot;', '"').replace('&amp;', '&') if cells else ""
                row_topics.append(c0)
                
            aligned = []
            for p_num, pl in all_pdf_lines:
                sims = [(_text_similarity(pl, rt), r_idx) for r_idx, rt in enumerate(row_topics)]
                best_sim, best_idx = max(sims, key=lambda x: x[0]) if sims else (0.0, -1)
                aligned.append({
                    'page': p_num,
                    'text': pl,
                    'sim': best_sim,
                    'match_idx': best_idx if best_sim >= 0.70 else None
                })
                
            for i in range(1, len(aligned) - 1):
                prev = aligned[i - 1]
                curr = aligned[i]
                nxt = aligned[i + 1]
                
                if curr['match_idx'] is None:
                    if prev['match_idx'] is not None and nxt['match_idx'] is not None:
                        if prev['page'] != curr['page'] or curr['page'] != nxt['page']:
                            continue
                        if prev['match_idx'] < nxt['match_idx'] and (nxt['match_idx'] - prev['match_idx'] <= 2):
                            c_text = curr['text']
                            if any(ign in c_text for ign in ['พิมพ์วันที่', 'Printed', 'BMW', 'Page', 'เอกสาร', 'คู่มือ', 'บีเอ็มดับเบิลยู', 'Effective', 'Z9']):
                                continue
                            if len(_simplify_text(c_text)) < 4:
                                continue
                                
                            simp_c = _simplify_text(c_text)
                            prev_text = _simplify_text(row_topics[prev['match_idx']])
                            nxt_text = _simplify_text(row_topics[nxt['match_idx']])
                            
                            # Skip if c_text is just a wrapped text fragment of adjacent rows
                            if simp_c in prev_text or simp_c in nxt_text:
                                continue
                            if _is_fuzzy_substring(c_text, row_topics[prev['match_idx']], 0.60) or _is_fuzzy_substring(c_text, row_topics[nxt['match_idx']], 0.60):
                                continue
                            if _text_similarity(c_text + " " + nxt['text'], row_topics[nxt['match_idx']]) >= 0.70 or _text_similarity(prev['text'] + " " + c_text, row_topics[prev['match_idx']]) >= 0.70:
                                continue
                            if _text_similarity(c_text, row_topics[prev['match_idx']]) >= 0.55 or _text_similarity(c_text, row_topics[nxt['match_idx']]) >= 0.55:
                                continue

                                
                            all_cell_texts = [_simplify_text(html.unescape(re.sub(r'<[^>]+>', '', c))) for c in re.findall(r'<td[^>]*>(.*?)</td>', harmonized_md, flags=re.DOTALL)]
                            if simp_c in all_cell_texts:
                                continue

                                
                            missing_text = c_text
                            prev_row_idx = prev['match_idx']
                            prev_row_full = full_rows[prev_row_idx].group(0)
                            
                            num_cols = len(re.findall(r'<td[^>]*>', prev_row_full))
                            if num_cols < 2:
                                num_cols = 2
                            val_cells = ''.join(['<td>■</td>'] * (num_cols - 1))
                            new_row_html = f"<tr><td>{missing_text}</td>{val_cells}</tr>"
                            
                            row_matches = list(re.finditer(re.escape(prev_row_full), harmonized_md))
                            if row_matches:
                                target_pos = row_matches[0].end()
                                harmonized_md = harmonized_md[:target_pos] + "\n" + new_row_html + harmonized_md[target_pos:]
        # --- Pattern 2C: Inter-Table Un-tabled Section Recovery ---
        # Checks if an entire section/page of equipment between the last equipment table and Paintwork was omitted by OCR
        all_tables_after = list(re.finditer(r'<table[^>]*>(.*?)</table>', harmonized_md, flags=re.DOTALL))
        last_eq_table = None
        paint_table = None
        for t in all_tables_after:
            t_c = t.group(1)
            if 'Paintwork' in t_c or 'สีตัวถัง' in t_c:
                paint_table = t
            elif '■' in t_c or '&#x25a0;' in t_c or '?' in t_c:
                last_eq_table = t
                
        if last_eq_table and paint_table:
            eq_rows = list(re.finditer(r'<tr[^>]*>(.*?)</tr>', last_eq_table.group(1), flags=re.DOTALL))
            if eq_rows:
                last_eq_cells = re.findall(r'<td[^>]*>(.*?)</td>', eq_rows[-1].group(0), flags=re.DOTALL)
                last_eq_topic = re.sub(r'<[^>]+>', '', last_eq_cells[0]).strip().replace('&#x27;', "'").replace('&quot;', '"').replace('&amp;', '&') if last_eq_cells else ""
                
                num_cols = 2
                for r in eq_rows:
                    td_count = len(re.findall(r'<td[^>]*>', r.group(0)))
                    if td_count > num_cols:
                        num_cols = td_count
                        
                idx_end = -1
                for idx, (p_num, pl) in enumerate(all_pdf_lines):
                    if _text_similarity(pl, "Paintwork") >= 0.8 or _text_similarity(pl, "สีตัวถัง") >= 0.8:
                        idx_end = idx
                        break
                        
                idx_start = -1
                if idx_end != -1:
                    for idx in range(idx_end - 1, -1, -1):
                        p_num, pl = all_pdf_lines[idx]
                        if _text_similarity(pl, last_eq_topic) >= 0.8:
                            idx_start = idx
                            break
                        
                if idx_start != -1 and idx_end != -1 and idx_end - idx_start > 1:
                    between_lines = all_pdf_lines[idx_start + 1:idx_end]
                    KNOWN_CAT_KEYWORDS = [
                        'Safety', 'Line / package', 'Transmission and technology', 'Exterior', 'Interior',
                        'Entertainment and communication', 'Equipment', 'ความปลอดภัย', 'ชุดตกแต่งพิเศษ',
                        'ระบบขับเคลื่อนและเทคโนโลยี', 'อุปกรณ์ภายนอก', 'อุปกรณ์ภายใน', 'ระบบความบันเทิงและการสื่อสาร'
                    ]
                    IGNORE_PATTERNS = [
                        'BMW', 'SPECIFICATIONS', 'Effective', 'Printed', 'พิมพ์วันที่', 'คู่มือ', 'Page', 'Z9',
                        'ZKK', 'ZLC', 'SCAN QR', 'FOR FURTHER', 'Range dependent', 'The privilege', 'reserves the right'
                    ]
                    all_cell_texts = [_simplify_text(html.unescape(re.sub(r'<[^>]+>', '', c))) for c in re.findall(r'<td[^>]*>(.*?)</td>', harmonized_md, flags=re.DOTALL)]
                    injected_rows = []

                    for p_num, pl in between_lines:
                        if any(ign.lower() in pl.lower() for ign in IGNORE_PATTERNS):
                            continue
                        if len(_simplify_text(pl)) < 4:
                            continue
                        if _is_fuzzy_substring(pl, last_eq_topic, 0.60):
                            continue
                        is_cat = any(_text_similarity(pl, k) >= 0.85 for k in KNOWN_CAT_KEYWORDS)

                        if is_cat:
                            injected_rows.append(f'<tr><td colspan="{num_cols}">{pl}</td></tr>')
                        else:
                            if _simplify_text(pl) not in all_cell_texts:
                                val_tds = ''.join(['<td>■</td>'] * (num_cols - 1))
                                injected_rows.append(f'<tr><td>{pl}</td>{val_tds}</tr>')
                                
                    if injected_rows:
                        # Append before </table> of last_eq_table
                        table_close_pos = last_eq_table.end() - len('</table>')
                        harmonized_md = harmonized_md[:table_close_pos] + '\n' + '\n'.join(injected_rows) + '\n' + harmonized_md[table_close_pos:]
                        print(f"   [HARMONIZER - Inter-Table Recovery] Recovered {len(injected_rows)} rows between '{last_eq_topic}' and Paintwork table")
    except Exception as e:
        print(f"   [HARMONIZER WARNING] Native PDF reconciliation encountered: {e}")
        
    with open(harmonized_md_path, "w", encoding="utf-8") as f:
        f.write(harmonized_md)
    print(f"   -> Intermediate Artifact Saved: {harmonized_md_path}")
    return harmonized_md


def extract_candidate_terms(md_content: str) -> list[str]:
    terms = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', md_content, flags=re.DOTALL):
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, flags=re.DOTALL)
        if not cells:
            continue
        
        first_cell = re.sub(r'<[^>]+>', '', cells[0]).strip()
        first_cell = first_cell.replace('&#x27;', "'").replace('&quot;', '"').replace('&amp;', '&')
        
        if first_cell and first_cell not in ['■', '-'] and not first_cell.isdigit() and len(first_cell) > 1:
            if not any(header in first_cell for header in ['คุณลักษณะเฉพาะ', 'รายละเอียดด้านเทคนิค', 'TECHNICAL DATA', 'Paintwork', 'สีตัวถังและวัสดุ']):
                if first_cell not in terms:
                    terms.append(first_cell)
                    
        # Scan value cells for descriptive text (excluding pure numbers, dashes, and checkmarks)
        for c in cells[1:]:
            c_clean = re.sub(r'<[^>]+>', '', c).strip().replace('&#x27;', "'").replace('&quot;', '"').replace('&amp;', '&')
            if not c_clean or c_clean in ['■', '-'] or len(c_clean) < 4:
                continue
            if not re.search(r'[a-zA-Zก-๙]', c_clean):
                continue
            text_without_nums = re.sub(r'[\d\s\/\,\.\-\:\;\(\)\%\*\+\~\=]', '', c_clean)
            if not text_without_nums or len(text_without_nums) < 2:
                continue
            pure_unit = re.sub(r'^(ซีซี|กก|กก\.|กิโลกรัม|ลิตร|วินาที|กม\.|กม\/ชม|กม\/ชม\.|มม\.|มิลลิเมตร|km\/h|rpm|cc|hp|kW|kg|l|s)$', '', text_without_nums.strip())
            if not pure_unit:
                continue
            if any(h in c_clean for h in ['คุณลักษณะเฉพาะ', 'รายละเอียดด้านเทคนิค', 'TECHNICAL DATA', 'Paintwork']):
                continue
            # Skip pure model header rows
            cell_texts = [re.sub(r'<[^>]+>', '', cl).strip() for cl in cells if cl.strip()]
            if len(cell_texts) > 1 and all(any(m in x for m in ['530e', '520d', '320d', '330e', 'M340i', 'Sport', 'Inspiring', 'M Sport', 'xDrive']) for x in cell_texts[1:]):
                continue
            if c_clean not in terms:
                terms.append(c_clean)
                
        if any(uph in row for uph in ['Leather', 'Sensatec', 'Vernasca', 'stitching', 'Stitching', 'หนัง']):
            for c in cells:
                c_clean = re.sub(r'<[^>]+>', '', c).strip().replace('&#x27;', "'").replace('&quot;', '"').replace('&amp;', '&')
                if c_clean and c_clean not in ['■', '-'] and len(c_clean) > 2:
                    if not any(m in c_clean for m in ['M Sport', 'xDrive', 'Paintwork']):
                        if c_clean not in terms:
                            terms.append(c_clean)
    return terms


def apply_text_corrections_to_markdown(raw_md: str, corrections: dict) -> str:
    if not corrections:
        return raw_md
        
    norm_corrections = {}
    for k, v in corrections.items():
        if k and v and k != v:
            norm_corrections[k.strip()] = v.strip()
            
    def replace_cell(match):
        attrs = match.group(1)
        inner_content = match.group(2)
        clean_inner = re.sub(r'<[^>]+>', '', inner_content).strip()
        clean_inner = clean_inner.replace('&#x27;', "'").replace('&quot;', '"').replace('&amp;', '&')
        
        if clean_inner in norm_corrections:
            new_text = norm_corrections[clean_inner]
            return f"<td{attrs}>{new_text}</td>"
        return match.group(0)

    pattern = r'<td([^>]*)>(.*?)</td>'
    cleaned_md = re.sub(pattern, replace_cell, raw_md, flags=re.DOTALL)
    return cleaned_md


def render_pdf_high_res_images(pdf_path: str, scale: float = 2.0) -> list[str]:
    """
    Renders each page of the PDF into a crisp, high-resolution PNG image (200% zoom, scale=2.0)
    using pypdfium2 so that small 6-8pt Thai fonts are rendered pin-sharp for Gemini Vision.
    """
    pdf = pdfium.PdfDocument(pdf_path)
    img_paths = []
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    temp_dir = tempfile.gettempdir()
    for idx, page in enumerate(pdf):
        img = page.render(scale=scale).to_pil()
        out_path = os.path.join(temp_dir, f"{base_name}_p{idx+1}_zoom200.png")
        img.save(out_path, format="PNG")
        img_paths.append(out_path)
    return img_paths


def section_1_multimodal_proofreader(raw_md: str, pdf_path: str, lang_code: str = "th") -> str:
    pdf_basename = os.path.basename(pdf_path)
    cleaned_md_path = f"multimodal_cleaned_{pdf_basename}.md"
    print(f"\n[SECTION 1] Starting Multimodal Text-Only Proofreader ({os.path.basename(pdf_path)})...")
    
    candidate_terms = extract_candidate_terms(raw_md)
    print(f"   -> Extracted {len(candidate_terms)} topic/category terms for proofreading.")
    
    t0 = time.time()
    client = get_gemini_client()
    
    # ─── 200% Zoom High-Resolution Rendering via pypdfium2 ────────────────────
    print(f"   -> Rendering PDF pages at 200% zoom (scale=2.0) via pypdfium2...")
    t_render = time.time()
    high_res_img_paths = render_pdf_high_res_images(pdf_path, scale=2.0)
    print(f"   -> Rendered {len(high_res_img_paths)} pages at 200% zoom in {time.time() - t_render:.2f}s")
    
    uploaded_files = []
    try:
        for p_idx, img_path in enumerate(high_res_img_paths, 1):
            print(f"   -> Uploading 200% Zoom Page {p_idx} to Gemini Files API...")
            up_f = client.files.upload(file=img_path)
            uploaded_files.append(up_f)
            print(f"   -> Page {p_idx} Uploaded successfully: {up_f.name}")
        
        prompt = PROMPT_MULTIMODAL_PROOFREADER_TH if lang_code == "th" else PROMPT_MULTIMODAL_PROOFREADER_EN
        full_prompt = f"{prompt}\n\nHere is the list of OCR terms to verify and correct against the 200% zoomed PDF pages:\n\n{json.dumps(candidate_terms, ensure_ascii=False, indent=2)}"
        
        contents = [*uploaded_files, full_prompt]
        
        corrections = None
        models_to_try = ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash"]
        for m_name in models_to_try:
            for attempt in range(4):
                try:
                    response = client.models.generate_content(
                        model=m_name,
                        contents=contents,
                        config=types.GenerateContentConfig(response_mime_type="application/json")
                    )
                    corrections = robust_json_loads(response.text)
                    if isinstance(corrections, list) and len(corrections) > 0:
                        corrections = corrections[0]
                    if isinstance(corrections, dict):
                        break
                except Exception as e:
                    wait_s = (attempt + 1) * 3
                    print(f"   -> Warning: {m_name} attempt {attempt+1} failed: {e}. Retrying in {wait_s}s...")
                    time.sleep(wait_s)
            if corrections is not None:
                break
        if corrections is None:
            raise RuntimeError("All models failed to generate content during proofreading.")
        
        actual_changes = {k: v for k, v in corrections.items() if k != v}
        print(f"[SECTION 1 SUCCESS] Proofreading complete in {time.time() - t0:.2f}s (Corrected {len(actual_changes)} terms)")
        
        # Apply text corrections directly to table cells in Python
        cleaned_text = apply_text_corrections_to_markdown(raw_md, corrections)
            
        with open(cleaned_md_path, "w", encoding="utf-8") as f:
            f.write(cleaned_text)
            
        print(f"   -> Intermediate Artifact Saved: {cleaned_md_path}")
        return cleaned_text
    finally:
        for up_f in uploaded_files:
            try:
                client.files.delete(name=up_f.name)
                print(f"   -> Cleaned up uploaded file from Gemini server: {up_f.name}")
            except Exception as e:
                print(f"   -> Warning: could not delete temporary Gemini file: {e}")
        for img_path in high_res_img_paths:
            try:
                if os.path.exists(img_path):
                    os.remove(img_path)
            except Exception:
                pass


def split_cleaned_markdown(cleaned_md: str) -> tuple[str, str]:
    lines = cleaned_md.split('\n')
    paint_start_idx = -1
    
    for idx, line in enumerate(lines):
        line_clean = line.strip().lower()
        if any(kw in line_clean for kw in ['paintwork', 'upholstery', 'สีตัวถัง', 'วัสดุภายใน', 'ลวดลาย/สีเบาะ']):
            for check_idx in range(idx, -1, -1):
                if lines[check_idx].strip().startswith("##") or "<table" in lines[check_idx].lower():
                    paint_start_idx = check_idx
                    break
            if paint_start_idx != -1:
                break
                
    if paint_start_idx == -1:
        specs_lines = lines
        paint_lines = []
    else:
        specs_lines = lines[:paint_start_idx]
        paint_lines = lines[paint_start_idx:]

        
    return '\n'.join(specs_lines), '\n'.join(paint_lines)


def section_2_specs_extractor(specs_md: str, lang_code: str = "th") -> dict:
    print(f"\n[SECTION 2] Extracting Specs & Standard Equipment (Pure Python HTML Parser)...")
    t0 = time.time()
    
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', specs_md, flags=re.DOTALL)
    if not rows:
        raise ValueError("No table rows found in specs_md.")
        
    first_row_cells = re.findall(r'<td[^>]*>(.*?)</td>', rows[0], flags=re.DOTALL)
    models = [
        re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', c)).strip()
        .replace('&#x27;', "'").replace('&quot;', '"').replace('&amp;', '&')
        for c in first_row_cells[1:]
    ]
    if not models:
        raise ValueError("No models found in header row.")
        
    model_data = {m: {} for m in models}
    current_category = "เครื่องยนต์และสมรรถนะ" if lang_code == "th" else "Engine and Performance"
    
    for r in rows[1:]:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', r, flags=re.DOTALL)
        cell_texts = [
            re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', c)).strip()
            .replace('&#x27;', "'").replace('&quot;', '"').replace('&amp;', '&')
            for c in cells
        ]
        if not cell_texts or not any(cell_texts):
            continue
            
        if len(cell_texts) == 1:
            cat_name = cell_texts[0]
            cat_name = cat_name.replace("$_{2}$", "₂").replace("_{2}", "₂").strip()
            if cat_name and not any(h in cat_name.upper() for h in ['คุณลักษณะเฉพาะ', 'รายละเอียดด้านเทคนิค', 'TECHNICAL DATA', 'SPECIFICATIONS']):
                current_category = cat_name
            continue
            
        topic = cell_texts[0]
        if any(h in topic.upper() for h in ['คุณลักษณะเฉพาะ', 'รายละเอียดด้านเทคนิค', 'TECHNICAL DATA', 'SPECIFICATIONS']):
            continue
            
        values = cell_texts[1:]
        
        for idx, m in enumerate(models):
            val = values[idx] if idx < len(values) else "-"
            if not val or val == "":
                val = "-"
            elif val == "■":
                val = "■"
                
            if current_category not in model_data[m]:
                model_data[m][current_category] = []
            model_data[m][current_category].append({"topic": topic, "value": val})
            
    final_models = []
    for m in models:
        specs_list = []
        for cat, details in model_data[m].items():
            specs_list.append({
                "category": cat,
                "details": details
            })
        final_models.append({
            "model_name": m,
            "specifications": specs_list
        })
        
    data = {
        "series": "BMW Specsheet",
        "models": final_models
    }
    print(f"[SECTION 2 SUCCESS] Specs extracted via Pure Python in {time.time() - t0:.4f}s (Models: {len(data.get('models', []))})")
    return data


def section_3_paint_extractor(paint_md: str, lang_code: str = "th") -> dict:
    if not paint_md.strip() or '<table' not in paint_md.lower():
        print(f"\n[SECTION 3] No Paintwork table present in brochure. Skipping Section 3 (Zero API call).")
        return {"series": "BMW Specsheet", "models": []}
        
    print(f"\n[SECTION 3] Extracting Paintwork & Upholstery Matrix (gemini-3.5-flash-lite)...")
    t0 = time.time()

    client = get_gemini_client()
    prompt = PROMPT_PAINT_TH if lang_code == "th" else PROMPT_PAINT_EN
    
    prompt += "\n\nCRITICAL CATEGORY REQUIREMENT: The category name for paintwork must strictly be 'Paintwork / สีตัวถังและวัสดุภายใน' for TH, and 'Paintwork & Upholstery' for EN."
    
    full_prompt = f"{prompt}\n\nHere is the CLEANED paintwork & upholstery matrix table content:\n\n{paint_md}"
    response = generate_with_fallback(client, full_prompt, is_json=True)
    
    data = robust_json_loads(response.text)
    if isinstance(data, list) and len(data) > 0:
        data = data[0]
        
    print(f"[SECTION 3 SUCCESS] Paintwork matrix extracted in {time.time() - t0:.2f}s (Models: {len(data.get('models', []))})")
    return data


def extract_pdf_footer_text(pdf_path: str) -> str:
    try:
        reader = pypdf.PdfReader(pdf_path)
        last_page = reader.pages[-1]
        text = last_page.extract_text()
        return text if text else ""
    except Exception as e:
        print(f"[WARN] Failed to read PDF footer: {e}")
        return ""


def apply_business_rules(final_output: dict, source_pdf_path: str, lang_code: str = "th"):
    """
    Injects deterministic external rules (AC charging notes for 5 Series, 800V for iX3, etc.)
    Zero AI cost, deterministic logic.
    """
    pdf_name = os.path.basename(source_pdf_path)
    
    # Rule 1: 5 Series AC Charging from official website
    if "5-20260417-01" in pdf_name:
        ac_map_th = {
            '530e Inspiring': ('11', '2 ชั่วโมง 15 นาที*', 'อ้างอิงจาก https://www.bmw.co.th/th/all-models/5-series/sedan/bmw-5-series-sedan-phev-overview.html'),
            '520d M Sport': ('-', '-', '-'),
            '530e M Sport': ('11', '2 ชั่วโมง 15 นาที*', 'อ้างอิงจาก https://www.bmw.co.th/th/all-models/5-series/sedan/bmw-5-series-sedan-phev-overview.html')
        }
        ac_map_en = {
            '530e Inspiring': ('11', '2 hours 15 minutes*', 'Referenced from https://www.bmw.co.th/th/all-models/5-series/sedan/bmw-5-series-sedan-phev-overview.html'),
            '520d M Sport': ('-', '-', '-'),
            '530e M Sport': ('11', '2 hours 15 minutes*', 'Referenced from https://www.bmw.co.th/th/all-models/5-series/sedan/bmw-5-series-sedan-phev-overview.html')
        }
        active_map = ac_map_th if lang_code == "th" else ac_map_en
        cat_engine = "เครื่องยนต์และสมรรถนะ" if lang_code == "th" else "Engine and Performance"
        cat_ref = "ข้อมูลเอกสารอ้างอิง" if lang_code == "th" else "Document References"
        top_pwr = "กำลังการชาร์จแบบกระแสสลับ (AC) สูงสุด (กิโลวัตต์)" if lang_code == "th" else "Maximum AC charging power (kW)"
        top_time = "ระยะเวลาในการชาร์จแบบกระแสสลับ (AC) จาก 0 - 100%" if lang_code == "th" else "AC charging time 0 - 100%"
        top_note = "หมายเหตุการชาร์จ AC" if lang_code == "th" else "AC Charging Reference Note"

        for m in final_output.get("models", []):
            mname = m.get("model_name")
            if mname in active_map:
                pwr, tm, nt = active_map[mname]
                for cat in m.get("specifications", []):
                    c_name = cat.get("category", "").strip().upper()
                    if c_name == cat_engine.upper():
                        cat["details"].append({"topic": top_pwr, "value": pwr})
                        cat["details"].append({"topic": top_time, "value": tm})
                    elif c_name == cat_ref.upper():
                        cat["details"].append({"topic": top_note, "value": nt})

    # Rule 2: iX3 800V append to sixth-gen eDrive
    if "iX3" in pdf_name:
        for m in final_output.get("models", []):
            if "iX3" in m.get("model_name", ""):
                for cat in m.get("specifications", []):
                    for d in cat.get("details", []):
                        if (lang_code == "th" and d.get("topic") == "มอเตอร์ไฟฟ้า") or \
                           (lang_code == "en" and d.get("topic") == "Electric motor"):
                            if "(800 V)" not in d.get("value", ""):
                                d["value"] = d["value"] + " (800 V)"

def apply_recovery_and_healing_rules(final_output: dict, source_pdf_path: str, lang_code: str = "th"):
    """
    Applies deterministic Python recovery and post-processing rules:
    1. Footnote Superscript Removal from Values
    2. Dynamic Series Grouping & Naming (i-family / M-family / XM / Core series)
    3. Blank Cell Recovery for Standard Safety/Tech
    4. Single Variant Auto Recovery
    """
    # ─── 1. Footnote Superscript Removal from Values ──────────────────────────────
    superscript_re = re.compile(r'[\u00b9\u00b2\u00b3\u2070\u2074-\u2079]')
    for model in final_output.get("models", []):
        for spec in model.get("specifications", []):
            for detail in spec.get("details", []):
                val = detail.get("value")
                if isinstance(val, str):
                    detail["value"] = superscript_re.sub('', val).strip()

    # ─── 2. Dynamic Series Grouping & Naming ──────────────────────────────────────
    model_names = [m.get("model_name", "").strip() for m in final_output.get("models", [])]
    new_series = final_output.get("series", "BMW Specsheet")
    for mname in model_names:
        if re.match(r'^i[0-9a-zA-Z]', mname):
            first_word = mname.split()[0]
            new_series = f"BMW {first_word}"
            break
        elif re.match(r'^M[23458](\s|$|[a-zA-Z])', mname) and not re.match(r'^M\d{3}', mname):
            m = re.match(r'^M\d', mname.split()[0])
            if m:
                new_series = f"BMW {m.group(0)}"
                break
        elif mname.startswith("XM"):
            new_series = "BMW XM"
            break
        elif re.match(r'^[2-8]\d{2}', mname):
            lead = mname[0]
            new_series = f"BMW {lead} Series"
            break
        elif re.match(r'^X[1-7]', mname):
            first_word = mname.split()[0]
            new_series = f"BMW {first_word[:2]}"
            break
        elif re.match(r'^Z4', mname):
            new_series = "BMW Z4"
            break
    else:
        pdf_base = os.path.basename(source_pdf_path)
        clean_base = re.sub(r'^(temp_|brochure_|download_)', '', pdf_base, flags=re.IGNORECASE)
        series_match = re.match(r'^([0-9]|iX?[0-9]|M[0-9]|X[0-9]|Z[0-9])', clean_base)
        if series_match:
            lead = series_match.group(1)
            if lead.isdigit():
                new_series = f"BMW {lead} Series"
    final_output["series"] = new_series

    # ─── 3. Blank Cell Recovery for Standard Safety/Tech (DEPRECATED & DISABLED) ───
    # Disabled by user request: Pure Python Stage 2 table parser already extracts ■ and -
    # verbatim from MinerU HTML tables. This heuristic was causing false-positive ■ on
    # non-standard equipment (e.g. 'ช่วงล่างถุงลม Adaptive 2-axle' matching 'ถุงลม').
    pass

    # ─── 4. Single Variant Auto Recovery ──────────────────────────────────────────
    if len(final_output.get("models", [])) == 1:
        model_data = final_output["models"][0]
        for spec in model_data.get("specifications", []):
            cat_name = spec.get("category", "")
            if cat_name in ("ข้อมูลเอกสารอ้างอิง", "Document References",
                            "มิติรถยนต์", "Dimension", "Dimensions",
                            "เครื่องยนต์และสมรรถนะ", "Engine and Performance",
                            "อัตราสิ้นเปลืองน้ำมันเชื้อเพลิง และระดับการปล่อย CO2", 
                            "Fuel consumption and CO2 emissions", "Fuel Consumption and CO2",
                            "การชาร์จแบบกระแสสลับ (AC)", "AC charging",
                            "ระยะเวลาในการชาร์จจาก 0 - 100%", "AC charging time 0 - 100%",
                            "การชาร์จแบบกระแสตรง (DC)", "DC charging",
                            "ระยะเวลาในการชาร์จจาก 10 - 80%", "DC charging time 10 - 80%") or \
               "Paintwork" in cat_name or "สีตัวถัง" in cat_name or "Upholstery" in cat_name:
                continue
            for detail in spec.get("details", []):
                d_topic = str(detail.get("topic", "")).lower()
                if d_topic in ("ล้อ", "ขนาดยาง", "wheel", "tyre", "tyre size", "wheels and tyres"):
                    continue
                if str(detail.get("value", "")).strip() in ("-", "", "None"):
                    detail["value"] = "■"

    # ─── 5. Whitespace, LaTeX & Quote Normalization for Topics and Values ─────────
    for model in final_output.get("models", []):
        for spec in model.get("specifications", []):
            if isinstance(spec.get("category"), str):
                c_name = re.sub(r'\$\s*\\text\{CO\}_2\s*\$', 'CO2', spec["category"])
                c_name = re.sub(r'\\text\{CO\}_2', 'CO2', c_name)
                spec["category"] = re.sub(r'\s+', ' ', c_name).strip()
            for detail in spec.get("details", []):
                if isinstance(detail.get("topic"), str):
                    t_name = re.sub(r'\$\s*\\text\{CO\}_2\s*\$', 'CO2', detail["topic"])
                    t_name = re.sub(r'\\text\{CO\}_2', 'CO2', t_name)
                    detail["topic"] = re.sub(r'\s+', ' ', t_name).strip()
                val = detail.get("value")
                if isinstance(val, str) and val not in ("■", "-"):
                    cleaned_val = re.sub(r'\$\s*\\text\{CO\}_2\s*\$', 'CO2', val)
                    cleaned_val = re.sub(r'\\text\{CO\}_2', 'CO2', cleaned_val)
                    cleaned_val = re.sub(r'\s+', ' ', cleaned_val).strip()
                    cleaned_val = cleaned_val.replace('‘', "'").replace('’', "'").replace('“', '"').replace('”', '"')
                    detail["value"] = cleaned_val


def section_4_json_assembler(specs_json: dict, paint_json: dict, source_pdf_path: str, lang_code: str = "th") -> dict:
    print(f"\n[SECTION 4] Assembling Final JSON & Footers via Pure Python (Zero API call)...")
    t0 = time.time()
    
    def normalize_name(name: str) -> str:
        return re.sub(r'[\s\(\)\-\_\/\\\,\.\:\;\'\"]', '', name).lower().strip()
        
    final_output = {
        "series": specs_json.get("series", "BMW Specsheet"),
        "pdf_source": os.path.basename(source_pdf_path),
        "models": []
    }
    
    paint_models_map = {}
    for pm in paint_json.get("models", []):
        mname = pm.get("model_name", "")
        if mname:
            paint_models_map[normalize_name(mname)] = pm
            
    for sm in specs_json.get("models", []):
        mname = sm.get("model_name", "")
        norm_mname = normalize_name(mname)
        
        filtered_specs = [
            c for c in sm.get("specifications", [])
            if c.get("category", "").strip() not in ("หมายเหตุ", "Notes")
        ]
        
        merged_model = {
            "model_name": mname,
            "specifications": filtered_specs
        }
        
        matched_pm = None
        for p_norm_key, p_obj in paint_models_map.items():
            if p_norm_key in norm_mname or norm_mname in p_norm_key:
                matched_pm = p_obj
                break
                
        if matched_pm:
            for p_spec in matched_pm.get("specifications", []):
                p_cat_name = "Paintwork / สีตัวถังและวัสดุภายใน" if lang_code == "th" else "Paintwork & Upholstery"
                p_spec["category"] = p_cat_name
                merged_model["specifications"].append(p_spec)
        else:
            print(f"[WARN] No paintwork matched for model: {mname}")
            
        final_output["models"].append(merged_model)
        
    footer_text = extract_pdf_footer_text(source_pdf_path)
    pub_date = "-"
    pack_codes = []
    
    for line in footer_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if "Effective from" in line or "Printed on" in line or "พิม" in line or "วันที่" in line:
            parts = line.split("|")
            date_part = parts[0].strip()
            date_part = re.sub(r'^(Effective from|Printed on|พิมพ์วันที่|พิมพวันที่|พิมพ์|พิมพ|วันที่)\s*', '', date_part)
            pub_date = date_part.strip()
        matches = re.findall(r'\([^)]*\)', line)
        for m in matches:
            if "Z" in m and m not in pack_codes:
                pack_codes.append(m.strip())
                
    num_models = len(final_output.get("models", []))
    while len(pack_codes) < num_models:
        pack_codes.append("-")
    pack_codes = pack_codes[:num_models]
    
    cat_doc = "ข้อมูลเอกสารอ้างอิง" if lang_code == "th" else "Document References"
    topic_date = "วันที่พิมพ์เอกสาร" if lang_code == "th" else "Publication Date"
    topic_pack = "รหัสแพ็กเกจ (Local Pack)" if lang_code == "th" else "Local package code"
    
    for idx, model in enumerate(final_output.get("models", [])):
        new_cat = {
            "category": cat_doc,
            "details": [
                {"topic": topic_date, "value": pub_date},
                {"topic": topic_pack, "value": pack_codes[idx]}
            ]
        }
        model["specifications"].append(new_cat)
        
    # Apply business rules (AC charging, 800V)
    apply_business_rules(final_output, source_pdf_path, lang_code=lang_code)
    
    # Apply recovery and healing rules (Single-variant recovery, Safety/Tech recovery, Footnotes, Dynamic series naming)
    apply_recovery_and_healing_rules(final_output, source_pdf_path, lang_code=lang_code)
    
    print(f"[SECTION 4 SUCCESS] Assembled {len(final_output['models'])} models in {time.time() - t0:.2f}s")
    return final_output


def run_extraction_pipeline(pdf_path: str, output_json_path: str, lang: str = "th") -> dict:
    """
    Main Production Entrypoint called by batch_extractor.py and CI/CD workflows.
    Runs the 4-Stage Hybrid Multimodal Cross-Referencing Pipeline.
    """
    print(f"\n=================================================================")
    print(f"[START] Hybrid Multimodal Pipeline: {os.path.basename(pdf_path)} ({lang.upper()})")
    print(f"=================================================================")
    t_total = time.time()
    
    # Stage 0: MinerU
    raw_md = run_mineru_stage(pdf_path, lang_code=lang)
    
    # Pre-Stage 1: Table Harmonizer (Dangling text & native PDF sequence reconciliation)
    harmonized_md = pre_stage_1_table_harmonizer(raw_md, pdf_path, lang_code=lang)
    
    # Stage 1: Multimodal Proofreader
    cleaned_md = section_1_multimodal_proofreader(harmonized_md, pdf_path, lang_code=lang)
    
    # Partition tables
    specs_md, paint_md = split_cleaned_markdown(cleaned_md)
    print(f"[SPLIT] Cleaned Markdown partitioned: Specs ({len(specs_md)} chars), Paint ({len(paint_md)} chars)")
    
    # Stage 2: Specs JSON Extractor
    partial_specs = section_2_specs_extractor(specs_md, lang_code=lang)
    
    # Stage 3: Paintwork Extractor
    partial_paint = section_3_paint_extractor(paint_md, lang_code=lang)
    
    # Stage 4: Assembler & Rule Injections
    final_json = section_4_json_assembler(partial_specs, partial_paint, pdf_path, lang_code=lang)
    
    # Apply Manual Overrides if configured
    try:
        from manual_override_manager import apply_overrides
        pdf_basename = os.path.basename(pdf_path)
        for model in final_json.get("models", []):
            apply_overrides(pdf_basename, model)
    except Exception as oe:
        print(f"[WARNING] Manual overrides check: {oe}")
        
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(final_json, f, ensure_ascii=False, indent=4)
        
    elapsed = time.time() - t_total
    print(f"\n[FINISHED] Complete Hybrid Multimodal Execution in {elapsed:.2f}s -> {output_json_path}")
    return final_json


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python mineru_extractor.py <pdf_path> <output_json_path> [--lang <th|en>]")
        sys.exit(1)
        
    pdf_in = sys.argv[1]
    json_out = sys.argv[2]
    
    lang_val = "th"
    if "--lang" in sys.argv:
        idx = sys.argv.index("--lang")
        if idx + 1 < len(sys.argv):
            lang_val = sys.argv[idx + 1]
            
    run_extraction_pipeline(pdf_in, json_out, lang=lang_val)
