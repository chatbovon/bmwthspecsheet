"""
mineru_extractor.py
===================
Automates PDF parsing using MinerU's Precision Extract API (v4) with VLM model,
and corrects extracted Markdown tables using Gemini API for structured JSON output.

Features:
  1. MinerU Precision API Client (v4): Gets presigned OSS URL, uploads PDF bytes,
     submits the OSS URL to the Precision Extract endpoint with vlm=True,
     polls for completion, downloads the result zip, and extracts Markdown.
  2. Secure Auth: API token loaded from .env file (MINERU_API_TOKEN). Never hardcoded.
  3. Table splitting & Gemini OCR correction with Key Pooling and Rotation.
  4. Deduplication and merging of multi-page specifications.

Required packages: requests, python-dotenv, pypdf, google-genai
"""

import os
import sys
import time
import json
import socket
import zipfile
import io
import requests

sys.stdout.reconfigure(encoding='utf-8')
from pypdf import PdfReader
from google import genai
from google.genai import types

# Load environment variables from .env file (MINERU_API_TOKEN, GEMINI_API_KEY, etc.)
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)  # Does not overwrite already-set env vars
except ImportError:
    pass  # dotenv is optional; env vars can be set manually

# Set default socket timeout to prevent hanging on network drops
socket.setdefaulttimeout(120)

# ─── API Setup ────────────────────────────────────────────────────────────────
# Load MinerU API token securely from environment / .env file.
# Generate token at: https://mineru.net/apiManage
MINERU_API_TOKEN = os.environ.get("MINERU_API_TOKEN", "").strip()

# Precision Extract API v4 base URL
PRECISION_BASE_URL = "https://mineru.net/api/v4"

if MINERU_API_TOKEN:
    print("[API] MinerU Precision API: Token loaded successfully.")
else:
    print("[API] ERROR: MINERU_API_TOKEN is not set. Please add it to your .env file.")
    sys.exit(1)

MINERU_HEADERS = {
    "Authorization": f"Bearer {MINERU_API_TOKEN}",
    "Content-Type": "application/json",
}

# Gemini API Key Pooling Configuration
API_KEYS = [
    os.environ.get("GEMINI_API_KEY_1", ""),
    os.environ.get("GEMINI_API_KEY_2", ""),
    os.environ.get("GEMINI_API_KEY_3", "")
]
API_KEYS = [k.strip() for k in API_KEYS if k.strip()]

if not API_KEYS:
    std_key = os.environ.get("GEMINI_API_KEY")
    if std_key:
        API_KEYS = [std_key.strip()]

if not API_KEYS:
    print("[ERROR] No Gemini API Keys found. Please set GEMINI_API_KEY or GEMINI_API_KEY_1/2/3.")
    sys.exit(1)

# Target Gemini model for OCR correction
MODEL_NAME = "gemini-3.5-flash"

# ─── System Prompts ───────────────────────────────────────────────────────────
PROMPT_TH = """You are an expert BMW Automotive Specification Analyst and Data Structuring Specialist.
Your task is to take a pre-extracted Markdown/HTML specification table from a BMW brochure, correct any OCR spelling mistakes (especially in Thai), and format the output into a strict JSON structure.

เป้าหมายของคุณคือ: ดึงข้อมูลสเปก "ทุกบรรทัด" และ "ทุกตัวอักษร" บนทุกหน้าของเอกสาร (รวมถึงอุปกรณ์มาตรฐานและออปชันระบบขับเคลื่อน อุปกรณ์ภายนอก อุปกรณ์ภายใน ความปลอดภัย และความบันเทิง) ห้ามตกหล่นแม้แต่ข้อเดียว เพื่อใช้เป็นข้อมูลอ้างอิงให้พนักงานขาย

กฎเหล็กที่ต้องปฏิบัติตามอย่างเคร่งครัด:
1. ห้ามสรุปความ ห้ามย่อความ ห้ามตัดออปชันย่อยทิ้งเด็ดขาด ต้องดึงข้อมูลมาแบบคำต่อคำ (Verbatim) ให้ครบทุกบรรทัดที่ปรากฏในตาราง
2. ในเอกสารจะมีตารางอุปกรณ์มาตรฐาน (เช่น ระบบขับเคลื่อน อุปกรณ์ภายนอก อุปกรณ์ภายใน ความปลอดภัย ความบันเทิง) บนหน้ากลางๆ (หน้า 2, 3, 4) คุณต้องดึงข้อมูลเหล่านี้มาให้ครบถ้วน ห้ามข้ามเด็ดขาด
3. **กฎการกู้คืนช่องว่างสำหรับอุปกรณ์มาตรฐาน (Blank Cell Recovery):** บางครั้งการสแกนหรือสกัดตารางอาจทำเครื่องหมายเช็กถูกหรือสัญลักษณ์สี่เหลี่ยมตกหล่น ส่งผลให้ช่องในตารางเป็นช่องว่างเปล่า ให้จัดการดังนี้:
   - หากช่องใดในตารางระบุเครื่องหมายขีด "-" หรือระบุว่า "ไม่มี" อย่างชัดเจน ให้ระบุเป็น "-" (ไม่มี)
   - หากช่องในตารางเป็นช่องว่างเปล่า "" แต่หัวข้อนั้นเป็นอุปกรณ์มาตรฐานความปลอดภัยหรือเทคโนโลยีพื้นฐานของรถ (เช่น ถุงลมนิรภัย/Airbags, จุดยึดเบาะนั่งสำหรับเด็ก ISOFIX, ระบบเบรก ABS, ระบบควบคุมเสถียรภาพการขับขี่ DSC, ระบบช่วยเสริมแรงเบรก Brake Assist, ระบบสัญญาณเตือนภัย Alarm System, ระบบ Teleservices, ระบบ Intelligent Emergency Call, ระบบ Comfort Access, ระบบปรับอากาศอัตโนมัติ, BMW Live Cockpit, แท่นชาร์จโทรศัพท์แบบไร้สาย เป็นต้น) คุณต้องระบุเป็น "■" (มีติดตั้ง) ให้กับทุกรุ่นย่อย เนื่องจากรถยนต์ BMW ระดับนี้จะมีอุปกรณ์เหล่านี้ติดตั้งเป็นมาตรฐานในทุกรุ่นอยู่แล้ว
   - สำหรับรุ่นย่อย M Sport (มีคำว่า M Sport ในชื่อรุ่นย่อยหรือซีรีส์) อุปกรณ์ตกแต่งมาตรฐานที่เป็น M Sport เช่น "พวงมาลัยหุ้มหนังดีไซน์ M" (M Leather steering wheel), "ชุดตกแต่ง M Sport", "ช่วงล่าง M Sport", "เพดานหลังคาภายในสี Anthracite" จะต้องระบุเป็น "■" เสมอแม้ว่าช่องในตารางจะว่างเปล่า
   - หากช่องในตารางระบุตัวเลขเชิงอรรถ (Footnote) หรือสัญลักษณ์ตัวอักษรใดๆ (เช่น "1", "2", "•", "L", "S") ให้มองว่าเป็น "■" (มีติดตั้ง) ห้ามนำตัวเลขหรือตัวอักษรเหล่านั้นไปเป็นค่า value ใน JSON
   - สำหรับออปชันทั่วไปอื่นๆ ที่มีความแตกต่างกันตามรุ่นย่อย: หากช่องในตารางเป็นช่องว่างเปล่า ให้ระบุเป็น "-" เท่านั้น ห้ามคัดลอกเครื่องหมายมาจากแถวอื่นหรือคอลัมน์อื่นเด็ดขาด
4. หากออปชันไหนระบุรายละเอียดที่แตกต่างกันในแต่ละรุ่นย่อย ให้ใส่รายละเอียดนั้นลงไปให้ตรงรุ่น
5. **(สำคัญมาก) สำหรับหมวดสีตัวถังและวัสดุภายใน (Paintwork & Upholstery):** ในโบรชัวร์จะเป็นตาราง Matrix จับคู่ระหว่างสีตัวถังภายนอก (แถว/Row) และสีเบาะ/วัสดุหนังภายใน (คอลัมน์/Column) โดยมีเครื่องหมายสี่เหลี่ยม (■ หรือ □) แสดงการจับคู่ ให้คุณสกัดข้อมูลดังนี้:
   - คุณต้องระบุรุ่นย่อยของรถให้ตรงกับตาราง (เช่น 740d M Sport, 750e xDrive M Sport, 320d M Sport เป็นต้น)
   - **การสกัดชื่อวัสดุเบาะหนังภายใน:** ในหัวคอลัมน์ของตาราง Upholstery มักจะมีแถวซ้อนกัน โดยแถวบนสุดจะระบุชนิดของหนังเบาะ (เช่น BMW Individual leather 'Merino', Vernasca leather, Sensatec perforated) และแถวถัดลงมาจะระบุสีเบาะ (เช่น Black, Mocha, Cognac)
   - **(สำคัญที่สุด) คุณต้องระบุชนิดหนังเบาะควบคู่กับสีเบาะเสมอ** โดยเขียนให้อยู่ในรูปแบบ `"ชนิดหนัง - สีเบาะ"` เช่น `"BMW Individual leather 'Merino' - Mocha"` หรือ `"Vernasca leather - Black"` หรือ `"Sensatec perforated - Cognac"`
   - สำหรับแต่ละสีตัวถังภายนอก (Paintwork) ในแถว:
     1. ไล่ดูในแนวนอนเพื่อหาเครื่องหมายจับคู่ (■ หรือ □ หรือตัวเลข/ตัวอักษรใดๆ)
     2. ตรวจสอบคอลัมน์เพื่อดูว่าตรงกับหนังเบาะและสีเบาะตัวไหน
     3. นำค่าหนังเบาะควบคู่สีเบาะทั้งหมดที่จับคู่ได้มาเขียนในช่อง value หากมีมากกว่าหนึ่งตัวให้คั่นด้วยลูกน้ำ (,) เช่น `"BMW Individual leather 'Merino' - Mocha, BMW Individual leather 'Merino' - Black"`
     4. หากแถวสีภายนอกใดไม่มีการจับคู่กับหนังเบาะเลย ให้ระบุเป็น "-"
   - **กรณีมีตารางหลายรุ่นย่อยซ้อนกันในแนวตั้ง (เช่น BMW 5 Series):**
     * ต้องอ่านและดึงข้อมูลของแต่ละตารางแยกกันตามลำดับจากบนลงล่างอย่างเข้มงวด
     * สำหรับตารางแรกสุดด้านบน (เช่น 530e Inspiring): ห้ามมองข้ามหรือข้ามบรรทัดแรกๆ เด็ดขาด (เช่น แถว Black Sapphire Metallic และ Mineral White Metallic จะต้องถูกเช็คสัญลักษณ์สี่เหลี่ยมและดึงสเปกสีเบาะออกมาด้วย ห้ามใส่เป็น "-" หากมีสัญลักษณ์ปรากฏ)
6. **(สำคัญมาก) สำหรับตารางอุปกรณ์มาตรฐานและตารางสเปกหลัก (ชื่อหัวข้อที่ยาวจนขึ้นบรรทัดใหม่):**
   - หากหัวข้อของตารางมีความยาวจนขึ้นบรรทัดใหม่ (เช่น บรรทัดแรกเขียนว่า 'ระบบเสียงรอบทิศทางคุณภาพสูง Bowers & Wilkins' และบรรทัดสองเขียนว่า 'Diamond') คุณต้องรวมข้อความเข้าด้วยกันเป็นหัวข้อเดียวใน JSON (เช่น 'ระบบเสียงรอบทิศทางคุณภาพสูง Bowers & Wilkins Diamond')
   - **การตรวจสอบเครื่องหมายคู่ตาราง:** ให้ระมัดระวังเป็นพิเศษหากสัญลักษณ์สี่เหลี่ยมดำ (■) ถูกพิมพ์อยู่เยื้องลงมาในระดับบรรทัดที่สอง (เช่น ตรงกับคำว่า 'Diamond') คุณต้องจับคู่สัญลักษณ์นี้เข้ากับหัวข้อหลักนั้น ห้ามนำไปสับสนหรือคิดว่าเป็นสัญลักษณ์ของแถวบน (เช่น Harman Kardon) หรือแถวล่างเด็ดขาด
   - **ห้ามลอกเลียนแบบหรือใส่เครื่องหมายในช่องว่าง:** หากช่องใดในตารางเป็นช่องว่างเปล่า (ไม่มีเครื่องหมาย ■) ให้ระบุเป็น "-" เท่านั้น ห้ามนำสัญลักษณ์ (■) จากแถวอื่นที่อยู่ใกล้เคียงมาใส่เด็ดขาด ตัวอย่างเช่น ในรุ่น **BMW XM (XM 50e และ XM 50e (Shadow Line))**:
     * แถว 'ระบบเครื่องเสียงรอบทิศทาง Harman Kardon' มีเครื่องหมาย (■) เฉพาะในคอลัมน์ที่ 1 (XM 50e) เท่านั้น ส่วนคอลัมน์ที่ 2 (XM 50e (Shadow Line)) เป็นช่องว่างเปล่า คุณต้องระบุรุ่นแรกเป็น "■" และรุ่นที่สองเป็น "-" เท่านั้น
     * แถว 'ระบบเสียงรอบทิศทางคุณภาพสูง Bowers & Wilkins Diamond' มีเครื่องหมาย (■) เฉพาะในคอลัมน์ที่ 2 (XM 50e (Shadow Line)) เท่านั้น ส่วนคอลัมน์ที่ 1 (XM 50e) เป็นช่องว่างเปล่า คุณต้องระบุรุ่นแรกเป็น "-" และรุ่นที่สองเป็น "■" เท่านั้น ห้ามตอบว่ารุ่นที่สองมีระบบเครื่องเสียงทั้งสองระบบเด็ดขาด
7. **(สำคัญมาก) ข้อมูลเอกสารอ้างอิง (Footer Information):** ที่ด้านล่างสุดของหน้ากระดาษ (Footer) จะมีข้อมูลวันที่พิมพ์และรหัส local pack ตัวอย่างเช่น "พิมพ์วันที่3 กรกฎาคม 2568 | (Z7J, Z8G), (Z7G, Z7U), (Z7H, Z8H)"
   - ให้สร้างหมวดหมู่ใหม่ชื่อว่า `"ข้อมูลเอกสารอ้างอิง"`
   - ดึงข้อมูลวันที่พิมพ์และใส่ลงในหัวข้อ `"วันที่พิมพ์เอกสาร"` (เช่น "3 กรกฎาคม 2568") ให้กับทุกรุ่นย่อย โดยใช้ค่าวันที่ที่ปรากฏใน footer ของเอกสาร (ห้ามแปลงรูปแบบหรือแปลภาษา)
   - ดึงรหัส local pack ที่อยู่ในวงเล็บมาเก็บแยกตามรุ่นย่อย โดยใช้กฎการเรียงลำดับจากซ้ายไปขวา (Sequential mapping from left to right) ให้ตรงกับคอลัมน์ของรุ่นย่อยใน specsheet เช่น วงเล็บแรกสุด `(Z7J, Z8G)` จะเป็นของรุ่นย่อยแรกสุดในตาราง, วงเล็บที่สอง `(Z7G, Z7U)` จะเป็นของรุ่นย่อยที่สอง และวงเล็บที่สาม `(Z7H, Z8H)` จะเป็นของรุ่นย่อยที่สาม ให้ใส่ลงในหัวข้อ `"รหัสแพ็กเกจ (Local Pack)"` (รวมวงเล็บ) ให้ตรงกับรุ่นย่อยนั้นๆ หากรุ่นย่อยใดไม่มีรหัส local pack ให้ใส่ "-"
8. **(สำคัญมาก) ห้ามรวมหรือยุบหมวดหมู่:** ห้ามนำรายละเอียดออปชันของหมวดหมู่หนึ่งไปรวมเข้ากับอีกหมวดหมู่หนึ่งเด็ดขาด (เช่น ห้ามนำออปชันของ อุปกรณ์ภายนอก หรือ อุปกรณ์ภายใน ไปใส่รวมไว้ใต้หมวดหมู่ ความปลอดภัย) ต้องสร้างคีย์ category แยกสำหรับแต่ละหมวดหมู่ให้ครบถ้วนในผลลัพธ์ JSON

หมวดหมู่ (Category) ที่ต้องปรากฏใน JSON (ห้ามตกหล่นหมวดหมู่เหล่านี้):
- เครื่องยนต์และสมรรถนะ
- อัตราสิ้นเปลืองน้ำมันเชื้อเพลิง และระดับการปล่อย CO2
- ล้อและยาง
- มิติรถยนต์
- ระบบขับเคลื่อนและเทคโนโลยี
- อุปกรณ์ภายนอก
- อุปกรณ์ภายใน
- ระบบความบันเทิงและการสื่อสาร (ระมัดระวังความถูกต้องของเครื่องเสียง Harman Kardon และ Bowers & Wilkins Diamond ในรุ่นย่อยต่างๆ ห้ามคัดลอกเครื่องหมายไปยังรุ่นที่ไม่มีโดยเด็ดขาด)
- ความปลอดภัย
- Paintwork / สีตัวถังและวัสดุภายใน (หรือชื่อใกล้เคียงในตาราง Paintwork)
- ข้อมูลเอกสารอ้างอิง

โครงสร้าง JSON ที่ตอบกลับมา ห้ามเพิ่ม Key อื่นนอกเหนือจากรูปแบบที่กำหนดนี้:
{
    "series": "[ชื่อซีรีส์ เช่น BMW 3 SERIES]",
    "models": [
        {
            "model_name": "[ชื่อรุ่นย่อยที่ 1 เช่น 320d M Sport]",
            "specifications": [
                {
                    "category": "[ชื่อหมวดหมู่ตาม PDF]",
                    "details": [
                        {
                            "topic": "[ชื่อหัวข้อ/ชื่อสีตัวถัง]",
                            "value": "[สเปกของรุ่นนี้ / หรือชื่อสีเบาะภายใน]"
                        }
                    ]
                }
            ]
        }
    ]
}
"""

PROMPT_EN = """You are a professional automotive technical specification extraction system. Your task is to read BMW PDF brochures in English and convert them into structured JSON.
Your goal is to: Extract "every line" and "every character" of technical specifications on all pages of the document (including standard equipment, optional equipment, exterior, interior, safety, and entertainment). Do not omit a single detail.

Strict rules to follow:
1. Do not summarize, do not shorten, do not omit sub-options. Extract everything word-for-word (verbatim) as it appears in the tables.
2. In the document, there will be standard equipment tables (e.g., Drivetrain, Exterior, Interior, Safety, Entertainment) on the middle pages. You must extract these completely. Do not skip them.
3. **Blank Cell Recovery Rule:** MinerU extraction sometimes fails to output checkmark symbols, resulting in empty/blank cells in the Markdown table. You must handle blank cells as follows:
   - If a cell contains an explicit dash "-" or "No", specify "-" (absent).
   - If a cell is blank/empty "" in the Markdown, but it represents a standard safety or universal technological feature (such as Airbags, ISOFIX child seat mounting, ABS, DSC, Dynamic Stability Control, Brake Assist, Alarm System, Teleservices, Intelligent Emergency Call, Comfort Access, Climate Control, BMW Live Cockpit, Wireless charging, etc.), you must output "■" (present) for all models. Modern BMW models always have these standard features.
   - For M Sport models (identifiable by M Sport in the model/series name), standard M Sport items like "M Leather steering wheel", "M Sport package", "M Sport suspension", "M Aerodynamics package" must be output as "■" even if the Markdown cell is blank.
   - If a cell contains a footnote number (like "1", "2") or a single character (like "•", "L", "S") that indicates option presence or footnote references in the PDF, map it as present "■". Never output raw numbers like "1" or "2" or character placeholders as values in the JSON.
   - For other normal features that vary by model: If a cell is blank, specify "-" only. Never copy symbols (■) from adjacent rows or columns to blank cells unless it falls under the standard safety/tech/M Sport categories above.
4. If an option specifies different details for each model, put the corresponding detail under each model.
5. **(Very Important) Paintwork & Upholstery Matrix:** In the brochure, there will be a matrix table indicating the combination of exterior paintwork (row) and interior upholstery/leather type (column). You must extract the data using these steps:
   - Identify the model name for each specific table (e.g., 740d M Sport, 750e xDrive M Sport, 320d M Sport, etc.).
   - **Extract Upholstery with Leather Type:** The column headers for Upholstery typically have nested rows where the top row indicates the leather/material type (e.g., "BMW Individual leather 'Merino'", "Vernasca leather", "Sensatec perforated") and the bottom row indicates the color (e.g., "Black", "Mocha", "Cognac").
   - **(Critical) You MUST always prefix the leather type to the upholstery color** in the format `"Leather Type - Color Name"`. Example values: `"BMW Individual leather 'Merino' - Mocha"`, `"Vernasca leather - Black"`, or `"Sensatec perforated - Cognac"`.
   - For each row (Paintwork / Paint color):
     1. Scan horizontally across the columns to locate the option indicators (such as ■, □, or any footnote numbers/marks).
     2. Trace vertically to find which upholstery column the symbol aligns with.
     3. Put the full upholstery descriptor (including leather type and color name) in the value field.
     4. If there are multiple matching combinations, join them with a comma (e.g., `"BMW Individual leather 'Merino' - Mocha, BMW Individual leather 'Merino' - Black"`).
     5. If a row has no symbol in any column, specify "-". Do not just write "Yes" or skip the row.
   - **When Paintwork tables are split and stacked vertically per model (e.g. BMW 5 Series):**
     * Process each table sequentially from top to bottom.
     * For the top-most table (e.g. 530e Inspiring): Be extremely vigilant. Do not skip or overlook the first few rows (such as Black Sapphire Metallic and Mineral White Metallic). You must check the symbols in all rows and map them to their corresponding upholstery descriptors correctly.
6. **(Very Important) Multi-line row labels in standard equipment and specification tables:**
   - If a row topic is long and wraps onto a second line (e.g. line 1: 'Bowers & Wilkins', line 2: 'Diamond'), you must join them into a single topic in your JSON output (e.g. 'Bowers & Wilkins Diamond').
   - **Aligning option symbols:** Pay extra attention if the black square symbol (■) is vertically placed on the second line of the wrapped text (e.g., horizontally aligned with the word 'Diamond'). You must correctly associate this symbol with the joined row topic, and NOT misalign or assign it to the row above (e.g. Harman Kardon) or the row below.
   - **Never copy symbols to blank cells:** If a cell is blank (no symbol) for a model, specify "-". Do not copy symbols (■) from adjacent rows or columns. For example, for the **BMW XM (XM 50e and XM 50e (Shadow Line))**:
     * The row 'Harman Kardon' has a symbol (■) only in Column 1 (XM 50e) and Column 2 (XM 50e (Shadow Line)) is blank. You must output Column 1 as "■" and Column 2 as "-".
     * The row 'Bowers & Wilkins Diamond' has a symbol (■) only in Column 2 (XM 50e (Shadow Line)) and Column 1 (XM 50e) is blank. You must output Column 1 as "-" and Column 2 as "■". Do not extract both audio systems as present ("■") for the same model.
7. **(Very Important) Footer Information (Document References):** At the bottom of pages (Footer), there will be metadata containing the publication date and local pack codes. For example: "Printed on 3 July 2026 | (Z7J, Z8G), (Z7G, Z7U), (Z7H, Z8H)"
   - Create a new category named `"Document References"`.
   - Extract the print date and put it under the topic `"Publication Date"` (e.g., "3 July 2026") for all models, using the date value in the document footer (do not translate or modify formatting).
   - Extract the local pack codes inside parentheses and map them sequentially from left to right to the corresponding columns (models) of the specsheet. For example, the first parentheses `(Z7J, Z8G)` goes to the first model, the second `(Z7G, Z7U)` to the second, and the third `(Z7H, Z8H)` to the third. Put this under the topic `"Package Code (Local Pack)"` (including parentheses) for each model. If a model doesn't have a package code, specify "-".
8. **(Very Important) Do not merge categories:** Do not combine options of one category into another (e.g., do not put Exterior or Interior options under Safety). You must create a separate category key for each group of specifications in the JSON output.

Categories expected in the JSON:
- Engine and Performance
- Fuel Consumption and CO2 Emission
- Wheels and Tyres
- Dimension
- Drivetrain and Technology
- Exterior Equipment
- Interior Equipment
- Entertainment and Communication (Be extremely careful with the values of Harman Kardon and Bowers & Wilkins Diamond systems across models. Do not copy checkmarks to columns/models where they are blank.)
- Safety
- Paintwork & Upholstery (or similar paint/upholstery category)
- Document References

JSON response structure:
{
    "series": "[Series name, e.g., BMW 3 SERIES]",
    "models": [
        {
            "model_name": "[Model name, e.g., 320d M Sport]",
            "specifications": [
                {
                    "category": "[Category name, e.g. Drivetrain and Technology]",
                    "details": [
                        {
                            "topic": "[Topic name, e.g., Transmission]",
                            "value": "[Value, e.g. ■ or - or text value]"
                        }
                    ]
                }
            ]
        }
    ]
}
"""

def _get_presigned_upload_url(file_name: str, max_retries: int = 5) -> tuple[str, str]:
    """
    Step 1 of Precision API (v4): Request a presigned OSS upload URL and batch task ID.
    Uses the POST /api/v4/file-urls/batch endpoint with full layout configuration.
    """
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
            
            # Extract batch_id and upload URL
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
    """
    Step 2: PUT raw PDF bytes to the presigned OSS URL.
    No custom headers should be sent to avoid invalidating the signature.
    """
    for attempt in range(max_retries):
        if attempt > 0:
            print(f"   [RETRY] Waiting 10s before OSS PUT retry {attempt+1}/{max_retries}...")
            time.sleep(10)
        try:
            print(f"   [UPLOAD] Uploading bytes to OSS...")
            with open(file_path, "rb") as f:
                # Do NOT pass MINERU_HEADERS (Authorization/Content-Type) to the OSS PUT request
                resp = requests.put(upload_url, data=f, timeout=120)
            if resp.status_code in (200, 204):
                print("   [UPLOAD] OSS upload succeeded.")
                return
            print(f"   [WARN] OSS PUT returned HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"   [WARN] OSS PUT failed: {e}")
    raise ValueError("Failed to upload file to OSS after all retries.")


def _poll_precision_task(batch_id: str, timeout: int = 900) -> str:
    """
    Step 3: Poll GET /extract-results/batch/{batch_id} until status/state=='success' or 'done'.
    Returns the Markdown content string.
    """
    poll_url = f"{PRECISION_BASE_URL}/extract-results/batch/{batch_id}"
    start_time = time.time()
    poll_interval = 15  # seconds between polls

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
            # Use 'state' primarily, fall back to 'status' if 'state' is empty
            state = str(result_item.get("state") or result_item.get("status") or "").lower()
            print(f"      [{elapsed}s] Status: {state}")

            if state in ("success", "done"):
                # Try direct md_url first; otherwise fall back to full_zip_url
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
            print(f"      [{elapsed}s] WARN: Poll error — {e}")

    raise TimeoutError(f"Precision batch task {batch_id} timed out after {timeout}s.")


def _download_result(url: str, max_retries: int = 5) -> str:
    """
    Step 4: Download result — either a raw .md file or a .zip archive.
    For zip: extracts and returns the first .md file found inside.
    """
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
            # ZIP result: extract the markdown from inside
            if "zip" in content_type or url.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    md_files = [n for n in zf.namelist() if n.endswith(".md")]
                    if not md_files:
                        raise ValueError(f"No .md file found in result zip. Contents: {zf.namelist()}")
                    # Use the largest .md file (the full content file)
                    md_name = max(md_files, key=lambda n: zf.getinfo(n).file_size)
                    print(f"   [EXTRACT] Reading '{md_name}' from zip ({zf.getinfo(md_name).file_size} bytes)")
                    return zf.read(md_name).decode("utf-8")
            else:
                # Plain markdown text
                return resp.text

        except zipfile.BadZipFile:
            # Response might actually be plain markdown despite content-type
            return resp.text
        except Exception as e:
            print(f"   [WARN] Download failed: {e}")
    raise ValueError(f"Failed to download result after {max_retries} attempts.")


def parse_pdf_via_api(file_path: str, lang_code: str = "th", max_retries: int = 5) -> str:
    """
    Full Precision Extract API pipeline:
      1. Request upload URLs & batch task ID from file-urls/batch with configuration
      2. Upload file bytes to the OSS upload URL
      3. Poll status on the batch task ID until complete
      4. Download and return Markdown content
    """
    file_name = os.path.basename(file_path)
    print(f"   [PRECISION] Starting Precision Extract for: {file_name}")

    # Step 1: Request OSS upload URL and batch_id
    upload_url, batch_id = _get_presigned_upload_url(file_name, max_retries)

    # Step 2: Upload PDF bytes to OSS
    _upload_to_oss(upload_url, file_path, max_retries)

    # Step 3: Poll status on the batch_id and retrieve Markdown
    return _poll_precision_task(batch_id)

# ─── Markdown Segmenter (Strictly Unchanged) ─────────────────────────────────
def split_tables_with_context(md_content: str) -> list[str]:
    """
    Groups markdown lines until the accumulated character size reaches max_chars,
    ensuring we do not split in the middle of a markdown or HTML table row.
    This limits the total number of segments to 2 or 3 per PDF file, reducing API calls.
    """
    lines = md_content.split('\n')
    segments = []
    
    current_segment = []
    current_len = 0
    max_chars = 7000
    
    for line in lines:
        current_segment.append(line)
        current_len += len(line) + 1
        
        # If we exceed max_chars and are not mid-table, perform split
        if current_len >= max_chars:
            stripped = line.strip()
            is_mid_table = stripped.startswith('|') or '<table' in stripped or '<tr>' in stripped or '<td>' in stripped
            if not is_mid_table:
                segments.append('\n'.join(current_segment))
                current_segment = []
                current_len = 0
                
    if current_segment:
        segments.append('\n'.join(current_segment))
        
    return segments if segments else [md_content]

# ─── Footer Extractor ────────────────────────────────────────────────────────
def extract_pdf_footer_text(pdf_path: str) -> str:
    """
    Extract footer text (print date, local pack codes) from PDF pages using pypdf.
    """
    footer_lines = []
    try:
        reader = PdfReader(pdf_path)
        for page in reader.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split("\n"):
                line_s = line.strip()
                # Check if this line is a footer containing date or package codes (typically starts with Z inside parentheses)
                if "พิมพ์วันที่" in line_s or "Printed on" in line_s or "Publication" in line_s or ("(" in line_s and ")" in line_s and "Z" in line_s):
                    if line_s not in footer_lines:
                        footer_lines.append(line_s)
    except Exception as e:
        print(f"[WARNING] Could not extract PDF footer: {e}")
    return "\n".join(footer_lines)

# ─── Segment Merger (Strictly Unchanged) ─────────────────────────────────────
def merge_spec_json_list(json_list: list[dict]) -> dict:
    """
    Combine list of segment extraction JSONs into a single model specsheet.
    Deduplicates topics by category and merges values using last-wins-for-dash.
    """
    if not json_list:
        return {}
        
    merged = {"series": "", "models": []}
    
    for j in json_list:
        if j.get("series") and not merged["series"]:
            merged["series"] = j["series"].strip()
            
    model_map = {}
    
    for j in json_list:
        for m in j.get("models", []):
            mname = m.get("model_name")
            if not mname:
                continue
            if mname not in model_map:
                model_map[mname] = {
                    "model_name": mname,
                    "specifications": []
                }
                merged["models"].append(model_map[mname])
                
            merged_model = model_map[mname]
            
            for spec in m.get("specifications", []):
                cat_name = spec.get("category")
                if not cat_name:
                    continue
                cat_ref = next((c for c in merged_model["specifications"] if c["category"] == cat_name), None)
                if not cat_ref:
                    cat_ref = {"category": cat_name, "details": []}
                    merged_model["specifications"].append(cat_ref)
                    
                topic_map = {d["topic"]: d for d in cat_ref["details"]}
                for detail in spec.get("details", []):
                    topic = detail.get("topic")
                    val = detail.get("value", "-")
                    if not topic:
                        continue
                    if topic not in topic_map:
                        cat_ref["details"].append(detail)
                        topic_map[topic] = detail
                    else:
                        existing = topic_map[topic]
                        if str(existing.get("value", "-")).strip() in ("-", "", "None") and \
                           str(val).strip() not in ("-", "", "None"):
                            existing["value"] = val
                            
    return merged

# ─── Pipeline Orchestrator ────────────────────────────────────────────────────
def run_extraction_pipeline(pdf_path: str, output_json_path: str, lang_code: str = "th"):
    """
    Orchestrates the entire extraction pipeline:
      1. Calls MinerU API to extract Markdown content from PDF.
      2. Segments the Markdown content.
      3. Passes segments to Gemini OCR Correction pipeline.
      4. Merges individual segment JSONs into a final specification JSON file.
    """
    print(f"[START] Processing PDF: {pdf_path}")
    if not os.path.exists(pdf_path):
        print(f"[ERROR] Source PDF not found: {pdf_path}")
        sys.exit(1)
        
    md_debug_path = output_json_path.rsplit(".", 1)[0] + "_raw.md"
    
    # Step 1: Call MinerU Agent API (or read existing raw markdown if available)
    if os.path.exists(md_debug_path):
        print(f"[MINERU] Found existing raw Markdown: {md_debug_path}. Skipping API call.")
        try:
            with open(md_debug_path, "r", encoding="utf-8") as f:
                md_content = f.read()
        except Exception as e:
            print(f"[WARNING] Could not read raw markdown from {md_debug_path}: {e}. Retrying API call.")
            os.remove(md_debug_path)
            
    if not os.path.exists(md_debug_path):
        try:
            md_content = parse_pdf_via_api(pdf_path, lang_code)
        except Exception as e:
            print(f"[FATAL] MinerU extraction failed: {e}")
            sys.exit(1)
            
        print("[MINERU] Successfully retrieved Markdown content.")
        
        # Save a temporary copy of the markdown content for inspection/debugging
        try:
            with open(md_debug_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            print(f"[DEBUG] Saved raw Markdown to: {md_debug_path}")
        except Exception as e:
            print(f"[WARNING] Could not save raw markdown debug file: {e}")
            
    # Extract PDF footer metadata directly using pypdf
    footer_text = extract_pdf_footer_text(pdf_path)
    if footer_text:
        print(f"[PDF] Extracted footer metadata:\n{footer_text}")
    else:
        print("[PDF] No footer metadata found in source PDF.")
        
    # Choose correct system prompt based on language
    system_prompt = PROMPT_TH if lang_code == "th" else PROMPT_EN
        
    # Step 2: Split Markdown by Table Segments
    segments = split_tables_with_context(md_content)
    print(f"[SEGMENT] Split into {len(segments)} segments.")
    
    # Step 3: Run OCR Correction pipeline using Gemini API Key Pooling & Fallback Models
    extracted_segments = []
    key_idx = 0
    model_pool = [MODEL_NAME, "gemini-3.1-flash-lite", "gemini-2.5-flash"]
    model_idx = 0
    
    for i, seg in enumerate(segments):
        print(f"   [API] Processing segment {i+1}/{len(segments)} via Gemini...")
        
        success = False
        attempts = 0
        max_attempts = len(API_KEYS) * len(model_pool) * 2  # Allow multiple retries per key/model combination
        while not success and attempts < max_attempts and len(API_KEYS) > 0:
            attempts += 1
            key = API_KEYS[key_idx]
            current_model = model_pool[model_idx]
            client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=60000))
            prompt = f"{system_prompt}\n\nHere is the input table segment:\n\n{seg}"
            if footer_text:
                prompt += f"\n\nHere is the footer metadata from the document page:\n{footer_text}"
            
            # Shift temperature slightly on retries to avoid repeating JSON syntax errors
            temp = min(0.6, (attempts - 1) * 0.2)
            if temp > 0.0 or model_idx > 0:
                print(f"      [RETRY] Attempt {attempts} using model={current_model}, temp={temp:.1f}...")
                
            try:
                response = client.models.generate_content(
                    model=current_model,
                    contents=[prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=temp
                    )
                )
                segment_json = json.loads(response.text)
                extracted_segments.append(segment_json)
                print(f"      -> Segment {i+1} OCR Correction OK.")
                success = True
            except Exception as e:
                err_msg = str(e)
                print(f"      [WARNING] Gemini Error on Key #{key_idx+1} ({current_model}): {e}")
                
                # Check for rate limit / quota exhaustion error and rotate model first
                if "RESOURCE_EXHAUSTED" in err_msg or "quota" in err_msg.lower() or "limit" in err_msg.lower():
                    model_idx = (model_idx + 1) % len(model_pool)
                    print(f"      [MODEL-FALLBACK] Rotated to model: {model_pool[model_idx]} due to quota/rate-limits.")
                    key_idx = (key_idx + 1) % len(API_KEYS)
                # Check for invalid API key authentication error and remove it
                elif "API key not valid" in err_msg or "API_KEY_INVALID" in err_msg or "INVALID_ARGUMENT" in err_msg:
                    print(f"      [REMOVE] Removing invalid API Key #{key_idx+1} from pool.")
                    API_KEYS.pop(key_idx)
                    if not API_KEYS:
                        print("[FATAL] All Gemini keys in pool have been removed as invalid.")
                        sys.exit(1)
                    key_idx = key_idx % len(API_KEYS)
                else:
                    key_idx = (key_idx + 1) % len(API_KEYS)
                    print(f"      [ROTATE] Rotated to Key #{key_idx+1}.")
                
        if not success:
            print(f"[FATAL] All Gemini keys/models failed to extract segment {i+1}.")
            sys.exit(1)
            
    # Step 4: Merge segments into a single unified JSON
    print("[MERGE] Merging segment JSONs...")
    merged_output = merge_spec_json_list(extracted_segments)
    # Add source file metadata to prevent merging with different PDF files
    merged_output["source_file"] = os.path.basename(pdf_path)
    merged_output["pdf_source"] = os.path.basename(pdf_path)
    
    # Step 5: Save final structured specsheet
    print(f"[SAVE] Saving JSON to: {output_json_path}")
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(merged_output, f, ensure_ascii=False, indent=4)
    print("[COMPLETE] Extraction pipeline finished successfully!")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python mineru_extractor.py <pdf_path> <output_json_path> [--lang <th|en>]")
        sys.exit(1)
        
    pdf_in = sys.argv[1]
    json_out = sys.argv[2]
    
    lang = "th"
    if "--lang" in sys.argv:
        idx = sys.argv.index("--lang")
        if idx + 1 < len(sys.argv):
            lang = sys.argv[idx + 1]
            
    run_extraction_pipeline(pdf_in, json_out, lang)
