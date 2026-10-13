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

sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
import pypdf
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
    models_to_try = ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.7-flash"]
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


# ─── PROMPTS ──────────────────────────────────────────────────────────────────

PROMPT_MULTIMODAL_PROOFREADER_TH = """คุณคือผู้เชี่ยวชาญด้านการตรวจทานเอกสารสเปกรถยนต์ BMW (Automotive Specification Proofreader)
คุณได้รับข้อมูล 2 ส่วนพร้อมกัน:
1. ไฟล์ PDF โบรชัวร์ต้นฉบับของ BMW (ใช้เป็น Visual Ground Truth ความถูกต้องสูงสุด)
2. ข้อความตาราง Raw Markdown/HTML ที่ระบบ OCR สกัดมาได้ (ใช้เป็นโครงสร้างตารางและตำแหน่งเครื่องหมาย)

เป้าหมายของคุณคือ:
นำข้อความในตาราง Raw Markdown/HTML ไปเทียบกับ "ภาพจริงบนหน้า PDF" เพื่อตรวจทานและแก้ไขคำสะกดผิด, สระลอย, วรรณยุกต์เพี้ยน หรือพยัญชนะที่ OCR อ่านผิดพลาด ให้ตรงกับตัวอักษรที่พิมพ์อยู่จริงบนเอกสาร PDF 100%

แนวทางการตรวจทานและแก้ไข (Cross-Referencing Rules):
1. **การเทียบภาพสายตา (Visual Verification):**
   - เมื่อตรวจพบคำใน Markdown ที่น่าสงสัย, พยัญชนะแปลก, หรือสระไม่สมบูรณ์ (เช่น "โทรศอก", "รังสี่", "ไฟล่องสว่าง", "เซ็มชัดนิภภัย", "คนชับ") ให้ก้มดูภาพบนหน้า PDF บริเวณตารางนั้นๆ ทันที
   - กู้คืนและแก้ไขตัวสะกดให้เป็นคำที่พิมพ์อยู่จริงใน PDF (เช่น "ปุ่มโทรออกฉุกเฉิน", "เคลือบสารกันรังสียูวี", "ชุดไฟส่องสว่าง...", "เข็มขัดนิรภัย...", "คนขับ")
2. **การคงคำศัพท์และเทคโนโลยีใหม่ (Verbatim Technology Preservation):**
   - หากบนหน้า PDF มีชื่อเทคโนโลยีใหม่, ออปชันใหม่, หรือสเปกเฉพาะรุ่น (เช่น ระบบการชาร์จใหม่, มอเตอร์ไฟฟ้า, จอ Panoramic ฯลฯ) ให้ยึดตามตัวสะกดจริงที่ปรากฏบน PDF 100% ห้ามดัดแปลง ห้ามเดาคำ และห้ามตัดทอน
3. **การแก้ไขชื่อหมวดหมู่:**
   - ตรวจดูหัวข้อหมวดหมู่ในตาราง ให้ตรงกับชื่อหมวดหมู่ที่พิมพ์ตัวหนา/แถบสีในหน้า PDF เสมอ (เช่น หาก OCR อ่านเป็น "อุปกรณ์กายใน" หรือ "ความบันเกิง" ให้แก้ไขเป็น "อุปกรณ์ภายใน" และ "ระบบความบันเทิงและการสื่อสาร" ตามที่ปรากฏใน PDF)

กฎเหล็กที่ห้ามละเมิดเด็ดขาด:
1. ยึดโครงสร้างตาราง (Tags: <table>, <tr>, <td> หรือเส้นตาราง |) จาก Markdown เป็นหลัก ห้ามลบแถว, ห้ามข้ามแถว, หรือรวมแถวโดยพลการ ทุกแถวที่อยู่ในตารางต้นทางต้องถูกรักษาไว้ครบ 100%
2. รักษาเครื่องหมายออปชันและความว่างเปล่าของเซลล์อย่างเคร่งครัด:
   - หากช่องใดว่างเปล่า (<td></td>) หรือเป็นขีด (-) ห้ามเติมเครื่องหมาย ■ เด็ดขาด ต้องคงความว่างหรือขีดไว้ตามเดิม
   - หากช่องใดมีเครื่องหมาย ■ ให้คงไว้เป็น ■
   - ห้ามขยับตำแหน่งเครื่องหมายข้ามคอลัมน์หรือข้ามแถวเด็ดขาด
3. ส่งกลับเฉพาะข้อความ Markdown/HTML ของตารางที่แก้ไขคำถูกต้องสมบูรณ์แล้วเท่านั้น ห้ามใส่คำอธิบายนำหน้าหรือลงท้าย
"""

PROMPT_MULTIMODAL_PROOFREADER_EN = """You are an expert Automotive Technical Specification Proofreader for official BMW brochures.
You are provided with two inputs simultaneously:
1. The original BMW PDF Brochure (Use as the Visual Ground Truth of ultimate correctness).
2. The Raw Markdown/HTML tables extracted by OCR (Use as the table structure and option checkmark anchor).

Your Sole Mission:
Cross-reference the text in the Raw Markdown/HTML tables against the actual visual pages of the PDF. Proofread and correct any character-level OCR misreadings, garbled words, broken hyphenation, or font glitches so that the text perfectly matches what is printed in the PDF brochure (100% fidelity).

Cross-Referencing Guidelines:
1. **Visual Proofreading:**
   - Whenever an OCR-extracted term looks garbled, typoed, or phonetically distorted in the Markdown table, inspect the corresponding visual table row in the PDF pages.
   - Restore and correct the spelling to exactly match the official text printed on the PDF page.
2. **Open-Domain Technology Preservation:**
   - For newly introduced technologies, trim packages, EV charging parameters, or model-specific features, keep and preserve the exact terminology as printed on the PDF pages verbatim. Do not alter, omit, or force them into different terms.
3. **Category Header Normalization:**
   - Verify category header texts against the bold category banner text visually visible in the PDF tables.

Strict Invariable Rules:
1. Maintain table integrity: never alter table structure, tags (<table>, <tr>, <td>), or column borders (|). NEVER omit, skip, or combine rows. Every single row in the input Markdown MUST be present in the output.
2. Maintain option checkmarks and empty cells with 100% exactness:
   - If a cell is empty or "-", keep it empty or "-"! NEVER fill in an empty cell with "■" just because another column has it or you think it should be standard.
   - If a cell has "■", keep it "■"!
   - Never shift checkmarks between columns or rows.
3. Return ONLY the sanitized, proofread Markdown/HTML table text without any conversation or markdown code fences.
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

def upload_pdf_bytes_to_oss(upload_url: str, pdf_bytes: bytes) -> bool:
    resp = requests.put(upload_url, data=pdf_bytes, timeout=120)
    return resp.status_code == 200

def get_precision_upload_url(filename: str = "document.pdf") -> dict:
    url = f"{PRECISION_BASE_URL}/file-urls/batch"
    payload = {"files": [{"name": filename}]}
    resp = requests.post(url, headers=MINERU_HEADERS, json=payload, timeout=30)
    resp.raise_ok = resp.status_code == 200
    if not resp.raise_ok:
        raise ValueError(f"Failed to get MinerU upload URL: {resp.text}")
    data = resp.json()
    if data.get("code") != 0:
        raise ValueError(f"MinerU error: {data.get('msg')}")
    return data["data"][0]

def extract_pdf_precision_oss(oss_url: str, lang_code: str = "th") -> str:
    url = f"{PRECISION_BASE_URL}/extract/precision/batch"
    payload = {
        "files": [{"url": oss_url}],
        "is_ocr": True,
        "vlm": True,
        "enable_table": True,
        "layout_model": "layoutlmv3"
    }
    resp = requests.post(url, headers=MINERU_HEADERS, json=payload, timeout=30)
    if resp.status_code != 200:
        raise ValueError(f"MinerU batch extraction failed: {resp.text}")
    data = resp.json()
    if data.get("code") != 0:
        raise ValueError(f"MinerU error: {data.get('msg')}")
    return data["data"]["batch_id"]

def poll_batch_result(batch_id: str, timeout_sec: int = 900) -> str:
    url = f"{PRECISION_BASE_URL}/extract-results/batch/{batch_id}"
    start = time.time()
    print(f"   [POLL] Polling batch {batch_id} (timeout={timeout_sec}s)...")
    while time.time() - start < timeout_sec:
        time.sleep(15)
        elapsed = int(time.time() - start)
        resp = requests.get(url, headers=MINERU_HEADERS, timeout=30)
        if resp.status_code != 200:
            continue
        data = resp.json()
        if data.get("code") != 0:
            continue
        extracts = data.get("data", {}).get("extracts", [])
        if not extracts:
            continue
        first = extracts[0]
        state = first.get("state")
        print(f"      [{elapsed}s] Status: {state}")
        if state == "done":
            return first["full_zip_url"]
        elif state == "failed":
            raise ValueError(f"MinerU extraction failed: {first.get('err_msg')}")
    raise TimeoutError(f"MinerU batch timed out after {timeout_sec}s.")

def download_and_extract_zip(zip_url: str) -> str:
    resp = requests.get(zip_url, timeout=120)
    if resp.status_code != 200:
        raise ValueError(f"Failed to download result zip: HTTP {resp.status_code}")
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        for name in z.namelist():
            if name.endswith("full.md") or name.endswith(".md"):
                with z.open(name) as f:
                    return f.read().decode("utf-8")
    raise ValueError("No markdown file found in MinerU result zip.")

def parse_pdf_via_api(pdf_path: str, lang_code: str = "th") -> str:
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    filename = os.path.basename(pdf_path)
    print(f"   [PRECISION] Starting Precision Extract for: {filename}")
    url_info = get_precision_upload_url(filename)
    upload_url = url_info["upload_url"]
    oss_url = url_info["url"]
    if not upload_pdf_bytes_to_oss(upload_url, pdf_bytes):
        raise ValueError("Failed to upload PDF bytes to OSS.")
    batch_id = extract_pdf_precision_oss(oss_url, lang_code=lang_code)
    zip_url = poll_batch_result(batch_id)
    return download_and_extract_zip(zip_url)

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


def section_1_multimodal_proofreader(raw_md: str, pdf_path: str, lang_code: str = "th") -> str:
    pdf_basename = os.path.basename(pdf_path)
    cleaned_md_path = f"multimodal_cleaned_{pdf_basename}.md"
    print(f"\n[SECTION 1] Starting Multimodal Visual Cross-Referencing (gemini-3.5-flash-lite)...")
    print(f"   -> Uploading PDF to Gemini Files API: {pdf_basename}")
    
    t0 = time.time()
    client = get_gemini_client()
    
    uploaded_file = client.files.upload(file=pdf_path)
    print(f"   -> PDF Uploaded successfully: {uploaded_file.name}")
    
    prompt = PROMPT_MULTIMODAL_PROOFREADER_TH if lang_code == "th" else PROMPT_MULTIMODAL_PROOFREADER_EN
    
    try:
        response = None
        models_to_try = ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.7-flash"]
        for m_name in models_to_try:
            for attempt in range(4):
                try:
                    response = client.models.generate_content(
                        model=m_name,
                        contents=[
                            uploaded_file,
                            f"{prompt}\n\nHere is the OCR Raw Markdown/HTML table content to cross-reference against the attached PDF:\n\n{raw_md}"
                        ]
                    )
                    break
                except Exception as e:
                    wait_s = (attempt + 1) * 3
                    print(f"   -> Warning: {m_name} attempt {attempt+1} failed: {e}. Retrying in {wait_s}s...")
                    time.sleep(wait_s)
            if response:
                break
        if not response:
            raise RuntimeError("All models failed to generate content.")
        
        cleaned_text = response.text.strip()
        if cleaned_text.startswith("```html") or cleaned_text.startswith("```markdown"):
            cleaned_text = re.sub(r"^```[a-zA-Z]*\n", "", cleaned_text)
            cleaned_text = re.sub(r"\n```$", "", cleaned_text)
            
        with open(cleaned_md_path, "w", encoding="utf-8") as f:
            f.write(cleaned_text)
            
        print(f"[SECTION 1 SUCCESS] Multimodal proofreading complete in {time.time() - t0:.2f}s")
        print(f"   -> Intermediate Artifact Saved: {cleaned_md_path}")
        return cleaned_text
    finally:
        try:
            client.files.delete(name=uploaded_file.name)
            print(f"   -> Cleaned up uploaded file from Gemini server: {uploaded_file.name}")
        except Exception as e:
            print(f"   -> Warning: could not delete temporary file: {e}")


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
        split_pt = int(len(lines) * 0.75)
        specs_lines = lines[:split_pt]
        paint_lines = lines[split_pt:]
    else:
        specs_lines = lines[:paint_start_idx]
        paint_lines = lines[paint_start_idx:]
        
    return '\n'.join(specs_lines), '\n'.join(paint_lines)


def section_2_specs_extractor(specs_md: str, lang_code: str = "th") -> dict:
    print(f"\n[SECTION 2] Extracting Specs & Standard Equipment (gemini-3.5-flash-lite)...")
    t0 = time.time()
    client = get_gemini_client()
    prompt = PROMPT_SPECS_TH if lang_code == "th" else PROMPT_SPECS_EN
    
    full_prompt = f"{prompt}\n\nHere is the CLEANED specification table content:\n\n{specs_md}"
    response = generate_with_fallback(client, full_prompt, is_json=True)
    
    data = json.loads(response.text)
    if isinstance(data, list) and len(data) > 0:
        data = data[0]
        
    print(f"[SECTION 2 SUCCESS] Specs extracted in {time.time() - t0:.2f}s (Models: {len(data.get('models', []))})")
    return data


def section_3_paint_extractor(paint_md: str, lang_code: str = "th") -> dict:
    print(f"\n[SECTION 3] Extracting Paintwork & Upholstery Matrix (gemini-3.5-flash-lite)...")
    t0 = time.time()
    client = get_gemini_client()
    prompt = PROMPT_PAINT_TH if lang_code == "th" else PROMPT_PAINT_EN
    
    prompt += "\n\nCRITICAL CATEGORY REQUIREMENT: The category name for paintwork must strictly be 'Paintwork / สีตัวถังและวัสดุภายใน' for TH, and 'Paintwork & Upholstery' for EN."
    
    full_prompt = f"{prompt}\n\nHere is the CLEANED paintwork & upholstery matrix table content:\n\n{paint_md}"
    response = generate_with_fallback(client, full_prompt, is_json=True)
    
    data = json.loads(response.text)
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
                    if cat.get("category") == cat_engine:
                        cat["details"].append({"topic": top_pwr, "value": pwr})
                        cat["details"].append({"topic": top_time, "value": tm})
                    elif cat.get("category") == cat_ref:
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
    
    # Stage 1: Multimodal Proofreader
    cleaned_md = section_1_multimodal_proofreader(raw_md, pdf_path, lang_code=lang)
    
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
