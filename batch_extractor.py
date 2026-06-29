import os
import json
import time
import sys
import socket
from google import genai
from google.genai import types
import page_splitter
import pdf_table_extractor as pte

# Set global socket timeout of 300 seconds to prevent hanging on network drops
socket.setdefaulttimeout(300)

# Fix Windows console encoding issues for Thai characters
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 1. API Model & Key Pooling Setup
# If the user explicitly overrides the model via environment variable, we use that model.
# Otherwise, we use the high-accuracy model chain.
override_model = os.environ.get("GEMINI_MODEL_NAME")
if override_model:
    MODEL_CHAIN = [override_model]
else:
    # [TEMP TEST] Lite model only — worktree experiment (gemini-3.1-flash-lite + page-by-page)
    MODEL_CHAIN = ["gemini-3.1-flash-lite"]

THREE_MODEL_FILES = {
    "i5-20240314-01_TH_edit.pdf",
    "M2-20250827-01_TH_Edit.pdf.asset.1758278358157.pdf",
    "5-20260417-01_TH.pdf.asset.1779074950693.pdf",
    "4-20241113-03_TH.pdf.asset.1745407581805.pdf",
    "3-20250625-01_TH.pdf.asset.1763550244972.pdf"
}

# Track models that have exceeded their daily limits across all keys
EXHAUSTED_MODELS = set()

API_KEYS = [
    os.environ.get("GEMINI_API_KEY_1", ""),
    os.environ.get("GEMINI_API_KEY_2", ""),
    os.environ.get("GEMINI_API_KEY_3", "")
]

# Filter out empty or whitespace-only keys
API_KEYS = [key.strip() for key in API_KEYS if key.strip()]

# Fallback to standard GEMINI_API_KEY if no pool keys are specified
if not API_KEYS:
    standard_key = os.environ.get("GEMINI_API_KEY")
    if standard_key:
        API_KEYS = [standard_key.strip()]

class APIKeyManager:
    def __init__(self, keys):
        self.keys = keys
        self.current_idx = 0
        print(f"[KEY_POOL] Start API Key Pooling with {len(self.keys)} keys")
        for i, key in enumerate(self.keys):
            masked = key[:6] + "..." + key[-6:] if len(key) > 12 else "Invalid/Short Key"
            print(f"   - Key #{i+1}: {masked}")

    def get_current_key(self):
        return self.keys[self.current_idx]

    def rotate_key(self):
        if len(self.keys) <= 1:
            print("[KEY_POOL] Only 1 API Key is available. Rotation skipped.")
            return self.get_current_key()
        self.current_idx = (self.current_idx + 1) % len(self.keys)
        masked = self.get_current_key()[:6] + "..." + self.get_current_key()[-6:] if len(self.get_current_key()) > 12 else "Invalid/Short Key"
        print(f"[ROTATE] Error detected! Rotating to API Key #{self.current_idx + 1} ({masked})")
        return self.get_current_key()

if not API_KEYS:
    print("[ERROR] No Gemini API Keys found. Please set GEMINI_API_KEY or GEMINI_API_KEY_1/2/3 in your environment variables.")
    sys.exit(1)

key_manager = APIKeyManager(API_KEYS)

# Prompt template from the original spec
PROMPT = """
คุณคือระบบสกัดข้อมูลทางเทคนิคของรถยนต์ระดับมืออาชีพ ทำหน้าที่อ่านโบรชัวร์ PDF ของ BMW และแปลงเป็น JSON
เป้าหมายของคุณคือ: ดึงข้อมูลสเปก "ทุกบรรทัด" และ "ทุกตัวอักษร" บนทุกหน้าของเอกสาร (รวมถึงอุปกรณ์มาตรฐานและออปชันระบบขับเคลื่อน อุปกรณ์ภายนอก อุปกรณ์ภายใน ความปลอดภัย และความบันเทิง) ห้ามตกหล่นแม้แต่ข้อเดียว เพื่อใช้เป็นข้อมูลอ้างอิงให้พนักงานขาย

กฎเหล็กที่ต้องปฏิบัติตามอย่างเคร่งครัด:
1. ห้ามสรุปความ ห้ามย่อความ ห้ามตัดออปชันย่อยทิ้งเด็ดขาด ต้องดึงข้อมูลมาแบบคำต่อคำ (Verbatim) ให้ครบทุกบรรทัดที่ปรากฏในตาราง
2. ในเอกสารจะมีตารางอุปกรณ์มาตรฐาน (เช่น ระบบขับเคลื่อน อุปกรณ์ภายนอก อุปกรณ์ภายใน ความปลอดภัย ความบันเทิง) บนหน้ากลางๆ (หน้า 2, 3, 4) คุณต้องดึงข้อมูลเหล่านี้มาให้ครบถ้วน ห้ามข้ามเด็ดขาด
3. สำหรับออปชันไหนที่ในตารางเป็นค่าว่าง (ไม่มีสัญลักษณ์เครื่องหมายคู่ในรุ่นนั้น) ให้ระบุ value เป็น "-" เท่านั้น ห้ามลอกเลียนแบบหรือดึงสัญลักษณ์ (■) จากแถวอื่นหรือคอลัมน์ข้างเคียงที่อยู่ใกล้กันมาใส่ในคอลัมน์ที่ว่างเปล่าเด็ดขาด ทุกออปชันและทุกรุ่นย่อยต้องสกัดค่าให้ตรงตามแถวและคอลัมน์จริงในตารางเท่านั้น
4. หากออปชันไหนระบุรายละเอียดที่แตกต่างกันในแต่ละรุ่นย่อย ให้ใส่รายละเอียดนั้นลงไปให้ตรงรุ่น
5. **(สำคัญมาก) สำหรับหมวดสีตัวถังและวัสดุภายใน (Paintwork):** ในโบรชัวร์จะใช้ตารางแบบ Matrix และมีสัญลักษณ์ "สี่เหลี่ยมสีดำ (■)" (หรือรูปภาพกล่องสี่เหลี่ยมขนาดเล็กที่บอกสเปกสี) เป็นตัวบอกการจับคู่สี ให้คุณดึงข้อมูลดังนี้:
   - ตรวจสอบชื่อรุ่นย่อยของตารางนั้นให้ชัดเจน (เช่น 530e Inspiring, 520d M Sport, 530e M Sport)
   - ระบุหัวข้อคอลัมน์ของตารางซึ่งก็คือวัสดุหุ้มเบาะ/สีเบาะภายใน (เช่น Black, Espresso Brown, Copper Brown/Atlas Grey)
   - สำหรับแต่ละแถว (สีตัวถัง/Paintwork):
     1. ไล่ดูทีละช่องในแนวนอนเพื่อหาเครื่องหมายสี่เหลี่ยมสีดำ (■)
     2. ตร�    - ดึงรหัส local pack ที่อยู่ในวงเล็บมาเก็บแยกตามรุ่นย่อย โดยใช้กฎการเรียงลำดับจากซ้ายไปขวา (Sequential mapping from left to right) ให้ตรงกับคอลัมน์ของรุ่นย่อยใน specsheet เช่น วงเล็บแรกสุด `(Z7J, Z8G)` จะเป็นของรุ่นย่อยแรกสุดในตาราง, วงเล็บที่สอง `(Z7G, Z7U)` จะเป็นของรุ่นย่อยที่สอง และวงเล็บที่สาม `(Z7H, Z8H)` จะเป็นของรุ่นย่อยที่สาม ให้ใส่ลงในหัวข้อ `"รหัสแพ็กเกจ"` (รวมวงเล็บ) ให้ตรงกับรุ่นย่อยนั้นๆ หากรุ่นย่อยใดไม่มีรหัส local pack ให้ใส่ "-"(■) หลายช่อง (จับคู่ได้หลายสี) ให้นำชื่อสีเบาะทั้งหมดมาเขียนรวมกันโดยคั่นด้วยเครื่องหมายลูกน้ำ (,) เช่น "Black, Mocha, Amarone"
     5. หากแถวไหนไม่มีสัญลักษณ์ (■) ปรากฏอยู่เลย ให้ระบุเป็น "-" ห้ามตอบแค่คำว่า "มี" หรือข้ามแถวนั้นเด็ดขาด
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

PROMPT_EN = """
You are a professional automotive technical specification extraction system. Your task is to read BMW PDF brochures in English and convert them into structured JSON.
Your goal is to: Extract "every line" and "every character" of technical specifications on all pages of the document (including standard equipment, optional equipment, exterior, interior, safety, and entertainment). Do not omit a single detail.

Strict rules to follow:
1. Do not summarize, do not shorten, do not omit sub-options. Extract everything word-for-word (verbatim) as it appears in the tables.
2. In the document, there will be standard equipment tables (e.g., Drivetrain, Exterior, Interior, Safety, Entertainment) on the middle pages. You must extract these completely. Do not skip them.
3. For options that are blank (no symbol/value for a model), specify the value as "-" only. Never copy or drag symbols (■) from adjacent rows or columns to blank cells. Every specification for each model must correspond strictly to its own row and column in the PDF table.
4. If an option specifies different details for each model, put the corresponding detail under each model.
5. **(Very Important) Paintwork & Upholstery Matrix:** In the brochure, there will be a matrix table with a black square symbol "■" (or a small vector square image) indicating the combination of paintwork (row) and upholstery (column). You must extract the data using these steps:
   - Identify the model name for each specific table (e.g. 530e Inspiring, 520d M Sport, 530e M Sport).
   - Identify the column headers which represent the upholstery colors (e.g. Black, Espresso Brown, Copper Brown/Atlas Grey).
   - For each row (Paintwork / Paint color):
     1. Scan horizontally across the columns to locate the black square symbol "■".
     2. Trace vertically to find which upholstery column the symbol aligns with.
     3. Put that upholstery name in the value field for the corresponding paint color and model.
     4. If there are multiple "■" symbols in the same row (matching multiple upholstery colors), join all upholstery names separated by a comma, e.g., "Black, Mocha, UpholsteryName".
     5. If a row has no symbol in any column, specify "-". Do not just write "Yes" or skip the row.
   - **When Paintwork tables are split and stacked vertically per model (e.g. BMW 5 Series):**
     * Process each table sequentially from top to bottom.
     * For the top-most table (e.g. 530e Inspiring): Be extremely vigilant. Do not skip or overlook the first few rows (such as Black Sapphire Metallic and Mineral White Metallic). You must check the symbols in all rows and map them to their corresponding upholstery colors correctly.
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
                    "category": "[Category name from PDF, e.g. Engine and Performance]",
                    "details": [
                        {
                            "topic": "[Topic/Paint name, e.g., Displacement (cc)]",
                            "value": "[Specification value, e.g., 1,995]"
                        }
                    ]
                }
            ]
        }
    ]
}
"""

# ==============================================================================
# PAGE-BY-PAGE DUAL-PDF EXTRACTION  —  Components 2-5
# ==============================================================================

# --- Component 2a: Lightweight prompt for header scan (page 0 only) -----------

PROMPT_COLUMN_SCAN = """
You are reading the first page of a BMW brochure specification table.
Your ONLY task: identify the sub-model names that appear as column headers
in the specification table, in order from LEFT TO RIGHT.

Return ONLY a JSON array of strings. Example:
["420i Coupé M Sport", "430i Coupé M Sport", "M440i xDrive"]

Do NOT add any other JSON keys, explanations, or markdown formatting.
If you cannot identify any column headers, return an empty array: []
"""


# --- Component 2b: scan_model_header_page() -----------------------------------

def scan_model_header_page(client, model_name: str,
                           th_page_path: str,
                           en_page_path: str = None) -> list:
    """
    Upload only the first-page single-page PDFs and ask Gemini to return the
    ordered list of sub-model column headers (left to right).

    Args:
        client:        An initialised genai.Client instance.
        model_name:    The Gemini model name to use for the scan.
        th_page_path:  Path to the TH single-page PDF (page 1 of source).
        en_page_path:  Path to the EN single-page PDF (optional, for context).

    Returns:
        Ordered list of sub-model name strings, e.g.:
            ["420i Coupé M Sport", "430i Coupé M Sport", "M440i xDrive"]
        Returns [] on any error (graceful degradation).
    """
    th_doc = None
    en_doc = None
    try:
        print(f"   [COLUMN_SCAN] Scanning column headers from page 1...")
        contents = []

        th_doc = client.files.upload(file=th_page_path)
        contents.append(th_doc)

        if en_page_path and os.path.exists(en_page_path):
            en_doc = client.files.upload(file=en_page_path)
            contents.append(en_doc)

        contents.append(PROMPT_COLUMN_SCAN)

        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0
            )
        )

        column_order = json.loads(response.text)
        if isinstance(column_order, list) and all(isinstance(x, str) for x in column_order):
            print(f"   [COLUMN_SCAN] Detected {len(column_order)} sub-model columns: {column_order}")
            return column_order
        else:
            print(f"   [COLUMN_SCAN] Unexpected response format — skipping column mapping.")
            return []

    except Exception as e:
        print(f"   [COLUMN_SCAN WARNING] Could not scan column headers: {e}. Proceeding without mapping context.")
        return []

    finally:
        for doc in [th_doc, en_doc]:
            if doc and client:
                try:
                    client.files.delete(name=doc.name)
                except Exception:
                    pass


# --- Component 4: build_page_prompt() -----------------------------------------

def build_page_prompt(base_prompt: str, column_order: list,
                      page_idx: int, total_pages: int,
                      target_column: str = None,
                      structured_table: str = None) -> str:
    """
    Inject page-context, column-mapping hints, and (optionally) a
    pdfplumber-extracted structured table into the base extraction prompt.

    Args:
        base_prompt:       The original PROMPT or PROMPT_SINGLE_VALIDATED string.
        column_order:      Ordered list of sub-model names from scan_model_header_page().
        page_idx:          Zero-based index of the current page being extracted.
        total_pages:       Total number of pages in the source PDF.
        target_column:     If provided, instruct AI to extract ONLY this column.
        structured_table:  Pre-extracted ASCII table from pdf_table_extractor.
                           When provided, AI trusts this table for checkbox values
                           and only needs to infer topic grouping + text values.

    Returns:
        Augmented prompt string.
    """
    column_lines = "\n".join(
        f'  Column {i + 1} \u2192 "{name}"'
        for i, name in enumerate(column_order)
    ) if column_order else "  (Column order could not be determined — infer from this page.)"

    page_context = f"""

[PAGE CONTEXT — DO NOT IGNORE]
You are extracting from page {page_idx + 1} of {total_pages} of a BMW spec brochure.
The sub-model columns appear LEFT TO RIGHT in this fixed order:
{column_lines}

Apply this column order strictly. If column headers are absent or abbreviated on
this page, use the mapping above — do NOT re-derive column order from partial
headers visible on this page alone.

IMPORTANT: If a category or topic from this page already exists in a previous
page extraction, your output for this page will be merged (union). Output ALL
data you find on THIS page. The merger will deduplicate by topic key.
"""

    if structured_table:
        page_context += f"""

[PRE-EXTRACTED CHECKBOX TABLE — HIGH CONFIDENCE]
The following table was extracted from this page using coordinate-based pixel
scanning (NOT AI inference). The CHECK/- values are mathematically accurate:
  CHECK = checkbox ■ is present in that column for that row
  -     = no checkbox in that column for that row

You MUST use these CHECK/- values as the authoritative source for all ■ symbols.
Do NOT override them based on visual inspection of the PDF.
Your task for these rows: assign each topic to the correct category and
copy the value as-is ("■" for CHECK, "-" for -).

{structured_table}

For rows NOT in this table (e.g. text-value rows like engine displacement,
paintwork colors, wheel descriptions), extract values from the PDF normally.
"""

    if target_column:
        page_context += f"""

[COLUMN FOCUS — STRICT]
Extract data ONLY for the sub-model column named: "{target_column}"
Do NOT extract or include any data for other sub-model columns.
Your "models" array MUST contain EXACTLY ONE entry with model_name="{target_column}".
"""

    return base_prompt + page_context


# --- Component 3: merge_page_results() ----------------------------------------

def merge_page_results(page_results: list) -> dict:
    """
    Merge a list of per-page extraction results (each in the standard
    {series, models:[...]} schema) into a single unified dict.

    Merge strategy:
    - series        : taken from page 1 result.
    - models        : union by model_name.
    - specifications: union by category name.
    - details       : union by topic key — first occurrence wins, no duplicates.
    - low_confidence_flags: all flags from all pages are concatenated.

    Args:
        page_results: List of dicts from per-page extract_pdf_with_retry() calls.
                      Items may be None (failed pages) — they are skipped.

    Returns:
        Single merged dict in the standard schema, or None if no valid page
        results are available.
    """
    valid_results = [r for r in page_results if r is not None]
    if not valid_results:
        return None

    merged = {"series": valid_results[0].get("series", ""), "models": []}

    # model_name -> {"specs": list, "cat_map": {cat_name: {"details": list, "topic_map": {topic: detail}}}}
    model_map = {}

    for page_data in valid_results:
        for model in page_data.get("models", []):
            name = model.get("model_name", "")
            if not name:
                continue

            if name not in model_map:
                model_map[name] = {"specs": [], "cat_map": {}}
                merged["models"].append({
                    "model_name": name,
                    "specifications": model_map[name]["specs"]
                })

            for cat in model.get("specifications", []):
                cat_name = cat.get("category", "")
                if not cat_name:
                    continue

                if cat_name not in model_map[name]["cat_map"]:
                    new_cat = {"category": cat_name, "details": []}
                    model_map[name]["specs"].append(new_cat)
                    model_map[name]["cat_map"][cat_name] = {
                        "ref": new_cat,
                        "topic_map": {}
                    }

                cat_entry = model_map[name]["cat_map"][cat_name]
                cat_ref   = cat_entry["ref"]
                topic_map = cat_entry["topic_map"]

                for detail in cat.get("details", []):
                    topic   = detail.get("topic", "")
                    new_val = detail.get("value", "-")
                    if not topic:
                        continue
                    if topic not in topic_map:
                        cat_ref["details"].append(detail)
                        topic_map[topic] = detail
                    else:
                        # Last-wins-for-dash: update if existing is "-" and new is not
                        existing = topic_map[topic]
                        if existing.get("value", "-") in ("-", "", None) and \
                           new_val not in ("-", "", None):
                            existing["value"] = new_val

    # Collect low_confidence_flags
    all_flags = []
    for page_data in valid_results:
        all_flags.extend(page_data.get("low_confidence_flags", []))
    if all_flags:
        merged["low_confidence_flags"] = all_flags

    print(f"   [MERGE] Merged {len(valid_results)} page results into "
          f"{len(merged['models'])} model(s).")
    return merged


# --- Component 3b: assemble_page_from_columns() --------------------------------

def assemble_page_from_columns(column_results: list, column_order: list) -> dict:
    """
    Combine N single-model results (one per column call) into a single
    multi-model page result in the standard {series, models} schema.

    Used by extract_pdf_page_by_page() when per-column mode is active.
    Columns whose extraction failed (None) are skipped — partial pages are
    better than a total failure.

    Args:
        column_results: List of per-column extraction dicts (or None on failure),
                        in the same order as column_order.
        column_order:   Ordered list of sub-model column names.

    Returns:
        Assembled {series, models} dict, or None if every column failed.
    """
    paired = list(zip(column_order, column_results))
    valid_pairs = [(name, res) for name, res in paired if res is not None]

    if not valid_pairs:
        return None

    series_name = valid_pairs[0][1].get("series", "")
    assembled = {"series": series_name, "models": []}

    for col_name, result in valid_pairs:
        models = result.get("models", [])
        if models:
            # Each column call returns exactly one model; take the first.
            assembled["models"].append(models[0])
        else:
            print(f"   [ASSEMBLE WARNING] Column '{col_name}': "
                  f"AI returned no model entry — skipping.")

    return assembled if assembled["models"] else None


# --- Component 5: extract_pdf_page_by_page() ----------------------------------

def extract_pdf_page_by_page(pdf_path: str, lang: str = "th") -> dict:
    """
    Independent page-by-page extraction orchestrator for BMW brochures.
    Processes the main PDF page-by-page without sending the other language's PDF.

    Flow:
        1. Split the PDF into single-page PDFs (scratch/tmp_pages/<lang>/).
        2. Scan page 1 to determine sub-model column order.
        3. For each page: call extract_pdf_with_retry() with single-page PDFs
           and an augmented prompt containing the column-mapping context.
        4. Merge all per-page results via merge_page_results().
        5. Verify the merged result.
        6. Clean up all temp page files.
        7. Return the merged dict (identical schema to whole-PDF extraction).

    Args:
        pdf_path:     Path to the brochure PDF to extract.
        lang:         Extraction language mode ("th" or "en").

    Returns:
        Merged extraction dict in the standard {series, models} schema,
        or None if extraction completely failed for all pages.
    """
    basename = os.path.basename(pdf_path)
    TMP_DIR = os.path.join("scratch", "tmp_pages", lang)

    page_paths = []

    try:
        # ------------------------------------------------------------------
        # STEP 1: Split the PDF into single-page PDFs
        # ------------------------------------------------------------------
        print(f"[PAGE_SPLIT] Splitting PDF: {basename}")
        page_paths = page_splitter.split_all_pages(pdf_path, TMP_DIR)
        print(f"   -> {len(page_paths)} page(s) written to '{TMP_DIR}'")

        total_pages = len(page_paths)

        # ------------------------------------------------------------------
        # STEP 2: Scan page 1 for column-to-model mapping
        # ------------------------------------------------------------------
        active_models = [m for m in MODEL_CHAIN if m not in EXHAUSTED_MODELS]
        scan_model = active_models[0] if active_models else MODEL_CHAIN[0]
        scan_client = genai.Client(
            api_key=key_manager.get_current_key(),
            http_options={'timeout': 60000}  # 60s is plenty for a 1-page scan
        )
        column_order = scan_model_header_page(
            scan_client, scan_model, page_paths[0], None
        )

        # ------------------------------------------------------------------
        # STEP 3: Per-page extraction loop
        # When column_order has >1 sub-model, use per-column mode:
        #   one dedicated API call per column → smaller context, less drift.
        # When column_order has <=1 entry (single-model PDF or scan failed),
        #   use whole-page mode.
        # ------------------------------------------------------------------
        use_per_column = len(column_order) > 1
        if use_per_column:
            print(f"[PER_COLUMN] {len(column_order)}-model PDF detected — "
                  f"per-column extraction enabled "
                  f"({total_pages} pages × {len(column_order)} cols = "
                  f"{total_pages * len(column_order)} API calls).")

        # ------------------------------------------------------------------
        # PRE-DETECT pdfplumber columns (once, from best header page)
        # ------------------------------------------------------------------
        pte_cols = None
        try:
            header_pg = min(1, total_pages - 1)
            pte_cols = pte.detect_columns(pdf_path, page_idx=header_pg)
            if not pte_cols:
                pte_cols = pte.detect_columns(pdf_path, page_idx=0)
            if pte_cols:
                print(f"[PTE] Columns detected: {[c.name for c in pte_cols]}")
            else:
                print(f"[PTE] Column detection failed — structured table disabled.")
        except Exception as e:
            print(f"[PTE WARNING] Column detection error (non-fatal): {e}")
            pte_cols = None

        page_results = []

        for page_idx in range(total_pages):
            page_file = page_paths[page_idx]

            print(f"\n[PAGE_EXTRACT] Page {page_idx + 1}/{total_pages}: "
                  f"{os.path.basename(page_file)}")

            # Select base prompt for this lang mode
            if lang == "th":
                from prompt_validation_th import PROMPT_SINGLE_VALIDATED
                base_prompt = PROMPT_SINGLE_VALIDATED
            else:
                base_prompt = PROMPT_EN

            # ------------------------------------------------------------------
            # Run pdfplumber pixel scan → structured table for this page
            # ------------------------------------------------------------------
            structured_table = None
            if pte_cols:
                try:
                    s_text, s_rows = pte.extract_page_structured(pdf_path, page_idx, pte_cols)
                    if s_text and pte.quality_check(s_rows):
                        structured_table = s_text
                        check_count = sum(
                            1 for r in s_rows
                            if any(v == '■' for v in r.values.values())
                        )
                        print(f"   [PTE] Page {page_idx+1}: {len(s_rows)} rows, "
                              f"{check_count} CHECK rows — table injected into prompt.")
                    else:
                        print(f"   [PTE] Page {page_idx+1}: quality check failed — "
                              f"using raw PDF only.")
                except Exception as pte_err:
                    print(f"   [PTE WARNING] Page {page_idx+1} error (non-fatal): {pte_err}")

            if use_per_column:
                # ---- Per-column mode: one API call per sub-model column ----
                column_results = []
                for col_idx, col_name in enumerate(column_order):
                    col_label = (f"page {page_idx + 1}/{total_pages}, "
                                 f"col {col_idx + 1}/{len(column_order)} "
                                 f'("{col_name}") of {basename}')
                    print(f"   [COLUMN_EXTRACT] {col_label}")

                    col_prompt = build_page_prompt(
                        base_prompt, column_order,
                        page_idx, total_pages,
                        target_column=col_name,
                        structured_table=structured_table
                    )
                    col_result = _extract_page_with_retry(
                        th_page_path=page_file,
                        en_page_path=None,
                        lang=lang,
                        override_prompt=col_prompt,
                        page_label=col_label
                    )
                    column_results.append(col_result)

                # Combine column results into a single page result
                page_result = assemble_page_from_columns(column_results, column_order)
                ok_count = sum(1 for r in column_results if r is not None)
                print(f"   [ASSEMBLE] Page {page_idx + 1}/{total_pages}: "
                      f"assembled {ok_count}/{len(column_order)} column(s).")

            else:
                # ---- Whole-page mode: one API call for all columns ----------
                augmented_prompt = build_page_prompt(
                    base_prompt, column_order, page_idx, total_pages,
                    structured_table=structured_table
                )
                page_result = _extract_page_with_retry(
                    th_page_path=page_file,
                    en_page_path=None,
                    lang=lang,
                    override_prompt=augmented_prompt,
                    page_label=f"page {page_idx + 1}/{total_pages} of {basename}"
                )

            if page_result is not None:
                page_results.append(page_result)
                print(f"   [PAGE_EXTRACT] Page {page_idx + 1} OK: "
                      f"{len(page_result.get('models', []))} model(s) found.")
            else:
                print(f"   [PAGE_EXTRACT WARNING] Page {page_idx + 1} failed "
                      f"(all models/keys exhausted). Skipping this page.")

        # ------------------------------------------------------------------
        # STEP 4: Merge all page results
        # ------------------------------------------------------------------
        print(f"\n[MERGE] Merging {len(page_results)}/{total_pages} successful page result(s)...")
        merged = merge_page_results(page_results)

        if merged is None:
            print(f"[FATAL] extract_pdf_page_by_page: all pages failed for {basename}.")
            return None

        # ------------------------------------------------------------------
        # STEP 5: Verify merged result
        # ------------------------------------------------------------------
        is_valid, validation_msg = verify_extracted_data(merged, lang=lang)
        if not is_valid:
            print(f"[ERROR] Merged result failed verification for {basename}: "
                  f"{validation_msg}")
            # Return the merged data even if verification fails — the caller
            # will decide whether to retry. Partial data is better than None.
            return None

        print(f"[PAGE_EXTRACT] {basename} — page-by-page extraction complete. "
              f"Series: '{merged['series']}', Models: {len(merged['models'])}")
        return merged

    finally:
        # ------------------------------------------------------------------
        # STEP 6: Always clean up temp page files
        # ------------------------------------------------------------------
        page_splitter.cleanup_temp_pages(TMP_DIR)



def _extract_page_with_retry(th_page_path: str,
                             en_page_path: str,
                             lang: str,
                             override_prompt: str,
                             page_label: str) -> dict:
    """
    Internal helper: call the Gemini API for a single-page PDF pair using a
    pre-built prompt, with full model-chain and key-rotation retry logic.

    This mirrors extract_pdf_with_retry() but accepts an explicit prompt
    (already augmented with column context) instead of selecting one internally.

    Args:
        th_page_path:    Path to the single-page TH PDF.
        en_page_path:    Path to the single-page EN PDF (may be None).
        lang:            Language mode for verify_extracted_data().
        override_prompt: Pre-built prompt string (base + column context).
        page_label:      Human-readable label for log messages.

    Returns:
        Extracted dict in the standard schema, or None on complete failure.
    """
    active_models = [m for m in MODEL_CHAIN if m not in EXHAUSTED_MODELS]
    if not active_models:
        active_models = [MODEL_CHAIN[-1]]
        print(f"[WARNING] All models exhausted. Forcing retry with: {active_models[0]}")

    for model_name in active_models:
        num_keys = len(key_manager.keys)
        all_keys_quota_exhausted = True

        for key_attempt in range(num_keys):
            current_key = key_manager.get_current_key()
            client = None
            th_doc = None
            en_doc = None
            try:
                client = genai.Client(
                    api_key=current_key,
                    http_options={'timeout': 120000}  # 2 min — single page is fast
                )
                print(f"   [EXTRACT] {page_label} | model={model_name} "
                      f"key=#{key_manager.current_idx + 1}/{num_keys}")

                th_doc = client.files.upload(file=th_page_path)
                contents = [th_doc]

                if en_page_path and os.path.exists(en_page_path):
                    en_doc = client.files.upload(file=en_page_path)
                    contents.append(en_doc)

                contents.append(override_prompt)

                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0
                    )
                )

                data = json.loads(response.text)

                if "series" not in data or "models" not in data:
                    raise ValueError(
                        f"AI output missing required keys ('series' or 'models') "
                        f"for {page_label}"
                    )

                # Lightweight check — don't require all categories on every page
                if not data.get("models"):
                    raise ValueError(f"No models found in page result for {page_label}")

                print(f"      -> OK: {len(data['models'])} model(s) returned.")
                return data

            except Exception as e:
                error_msg = str(e)
                print(f"   [ERROR] {page_label} | model={model_name} "
                      f"key=#{key_manager.current_idx + 1}: {error_msg}")

                is_rate_limit = any(
                    term in error_msg.lower()
                    for term in ["429", "limit", "exhausted", "quota", "503", "unavailable"]
                )
                is_daily_limit = False
                if is_rate_limit:
                    if any(
                        term in error_msg.lower()
                        for term in ["limit: 20", "limit: 0", "daily", "day", "quota exceeded"]
                    ):
                        is_daily_limit = True

                if not is_daily_limit:
                    all_keys_quota_exhausted = False

                key_manager.rotate_key()
                sleep_time = 20 if is_rate_limit else 3
                if is_rate_limit:
                    print(f"      -> [RATE_LIMIT] Waiting {sleep_time}s...")
                time.sleep(sleep_time)

            finally:
                # Ensure uploaded files are always deleted even on success
                for doc in [th_doc, en_doc]:
                    if doc and client:
                        try:
                            client.files.delete(name=doc.name)
                        except Exception:
                            pass

        if all_keys_quota_exhausted:
            print(f"[EXHAUSTED] Model '{model_name}' daily limit hit across all keys.")
            EXHAUSTED_MODELS.add(model_name)
        else:
            print(f"[INFO] All keys tried for model {model_name}. Falling back...")

    print(f"[FATAL] All models and keys failed for {page_label}.")
    return None


# ==============================================================================
# END OF PAGE-BY-PAGE COMPONENTS
# ==============================================================================

def verify_extracted_data_en(data):
    if not isinstance(data, dict):
        return False, "Data structure is not a Dictionary"
        
    if "models" not in data or not data["models"]:
        return False, "No models data found"
        
    for model in data["models"]:
        specs = model.get("specifications", [])
        if not specs:
            return False, f"Model {model.get('model_name')} has no specifications"
            
        if len(specs) < 7:
            return False, f"Model {model.get('model_name')} has too few categories ({len(specs)})"
            
        categories = {s.get("category", "") for s in specs}
        critical_categories = ["Exterior", "Interior", "Safety"]
        missing_critical = [c for c in critical_categories if not any(c.lower() in cat.lower() for cat in categories)]
        
        if missing_critical:
            return False, f"Model {model.get('model_name')} is missing critical categories: {', '.join(missing_critical)}"
            
        # Check and flag missing footer references instead of returning False
        ref_cat = next((s for s in specs if "Document References" in s.get("category", "")), None)
        if not ref_cat:
            if "low_confidence_flags" not in data:
                data["low_confidence_flags"] = []
            data["low_confidence_flags"].append({
                "model_name": model.get("model_name"),
                "category": "Document References",
                "topic": "Document References Category",
                "type": "Missing Footer References",
                "reason": "Missing Document References category in output"
            })
            print(f"[VERIFY_WARNING] Model {model.get('model_name')} is missing Document References category (Flagged)")
        else:
            details = ref_cat.get("details", [])
            topics = {d.get("topic", "") for d in details}
            required_topics = ["Publication Date", "Package Code (Local Pack)"]
            missing_topics = [t for t in required_topics if t not in topics]
            if missing_topics:
                if "low_confidence_flags" not in data:
                    data["low_confidence_flags"] = []
                for mt in missing_topics:
                    data["low_confidence_flags"].append({
                        "model_name": model.get("model_name"),
                        "category": "Document References",
                        "topic": mt,
                        "type": "Missing Footer References",
                        "reason": f"Missing critical reference topic: {mt}"
                    })
                print(f"[VERIFY_WARNING] Model {model.get('model_name')} is missing reference topics: {', '.join(missing_topics)} (Flagged)")
            
    return True, "Data is complete"

def verify_extracted_data(data, lang="th"):
    """
    ตรวจสอบความสมบูรณ์ของข้อมูลที่สกัดออกมา
    """
    if lang == "en":
        return verify_extracted_data_en(data)

    if not isinstance(data, dict):
        return False, "โครงสร้างข้อมูลไม่ใช่ Dictionary"
        
    if "models" not in data or not data["models"]:
        return False, "ไม่มีข้อมูลรุ่นย่อย (models)"
        
    for model in data["models"]:
        specs = model.get("specifications", [])
        if not specs:
            return False, f"รุ่น {model.get('model_name')} ไม่มีหมวดหมู่สเปก"
            
        # ตรวจสอบจำนวนหมวดหมู่ขั้นต่ำ
        if len(specs) < 7:
            return False, f"รุ่น {model.get('model_name')} มีหมวดหมู่สเปกน้อยเกินไป ({len(specs)} หมวดหมู่) คาดว่าเกิดข้อมูลตกหล่น"
            
        # ตรวจสอบความปลอดภัย อุปกรณ์ภายนอก อุปกรณ์ภายใน
        categories = {s.get("category", "") for s in specs}
        critical_categories = ["อุปกรณ์ภายนอก", "อุปกรณ์ภายใน", "ความปลอดภัย"]
        missing_critical = [c for c in critical_categories if not any(c in cat for cat in categories)]
        
        if missing_critical:
            return False, f"รุ่น {model.get('model_name')} ขาดหมวดหมู่สำคัญ: {', '.join(missing_critical)}"
            
        # Check and flag missing footer references instead of returning False
        ref_cat = next((s for s in specs if "ข้อมูลเอกสารอ้างอิง" in s.get("category", "")), None)
        if not ref_cat:
            if "low_confidence_flags" not in data:
                data["low_confidence_flags"] = []
            data["low_confidence_flags"].append({
                "model_name": model.get("model_name"),
                "category": "ข้อมูลเอกสารอ้างอิง",
                "topic": "หมวดหมู่ข้อมูลเอกสารอ้างอิง",
                "type": "Missing Footer References",
                "reason": "ไม่พบหมวดหมู่ข้อมูลเอกสารอ้างอิงในผลลัพธ์การสกัด"
            })
            print(f"[VERIFY_WARNING] รุ่น {model.get('model_name')} ไม่มีหมวดหมู่ ข้อมูลเอกสารอ้างอิง (Flagged)")
        else:
            details = ref_cat.get("details", [])
            topics = {d.get("topic", "") for d in details}
            required_topics = ["วันที่พิมพ์เอกสาร", "รหัสแพ็กเกจ"]
            missing_topics = [t for t in required_topics if t not in topics]
            if missing_topics:
                if "low_confidence_flags" not in data:
                    data["low_confidence_flags"] = []
                for mt in missing_topics:
                    data["low_confidence_flags"].append({
                        "model_name": model.get("model_name"),
                        "category": "ข้อมูลเอกสารอ้างอิง",
                        "topic": mt,
                        "type": "Missing Footer References",
                        "reason": f"ขาดหัวข้ออ้างอิงที่จำเป็น: {mt}"
                    })
                print(f"[VERIFY_WARNING] รุ่น {model.get('model_name')} ขาดหัวข้ออ้างอิง: {', '.join(missing_topics)} (Flagged)")
            
    return True, "ข้อมูลสมบูรณ์"

def find_matching_english_pdf(th_filename):
    if "_TH" not in th_filename:
        return None
    prefix = th_filename.split("_TH")[0] + "_EN"
    en_folders = ["bmw_brochures_auto_en", "bmw_brochures_custom_en"]
    for folder in en_folders:
        if os.path.exists(folder):
            for f in os.listdir(folder):
                if f.startswith(prefix) and f.lower().endswith(".pdf"):
                    return os.path.join(folder, f)
    return None

def find_matching_thai_pdf(en_filename):
    if "_EN" not in en_filename:
        return None
    prefix = en_filename.split("_EN")[0] + "_TH"
    th_folders = ["bmw_brochures_auto", "bmw_brochures_custom"]
    for folder in th_folders:
        if os.path.exists(folder):
            for f in os.listdir(folder):
                if f.startswith(prefix) and f.lower().endswith(".pdf"):
                    return os.path.join(folder, f)
    return None

def extract_pdf_with_retry(pdf_path, en_pdf_path=None, lang="th", max_retries=3):
    filename = os.path.basename(pdf_path)
    
    # Select prompt based on language and availability of English PDF for cross-validation
        # Load Thai JSON database for English cross-checking
    th_json_data = None
    if lang == "en":
        th_db_path = "bmw_master_specs.json"
        if os.path.exists(th_db_path):
            try:
                import json
                with open(th_db_path, "r", encoding="utf-8") as f:
                    th_db = json.load(f)
                prefix = filename.split("_EN")[0]
                th_entry = next((e for e in th_db if e.get("pdf_source", "").split("_TH")[0] == prefix), None)
                if th_entry:
                    th_json_data = th_entry
            except Exception as e:
                print(f"   [WARNING] Failed to load matching Thai JSON data: {e}")

    # Select prompt based on language and availability of other PDF
    if lang == "en":
        if th_json_data:
            prompt = PROMPT_EN + f"\n\nHere is the already-extracted Thai JSON data for this model. Use this to cross-check options, values, and details. If you find any discrepancies (e.g. options enabled in the Thai JSON but not in the English PDF, or vice-versa), you MUST write a detail entry in the 'low_confidence_flags' list of the output JSON:\n\n{json.dumps(th_json_data, ensure_ascii=False, indent=2)}"
            print(f"[VALIDATE] Found matching Thai JSON data. Appended to prompt context for Triple-Checking.")
        else:
            prompt = PROMPT_EN
            print(f"[VALIDATE] No matching Thai JSON data found.")
    else:
        if en_pdf_path:
            from prompt_validation_th import PROMPT_DUAL_VALIDATED
            prompt = PROMPT_DUAL_VALIDATED
            print(f"[VALIDATE] Found matching PDF: {os.path.basename(en_pdf_path)}. Using Dual-PDF cross-lingual validation.")
        else:
            from prompt_validation_th import PROMPT_SINGLE_VALIDATED
            prompt = PROMPT_SINGLE_VALIDATED
            print(f"[VALIDATE] No matching PDF found. Using Single-PDF logical validation.")
            
    # Filter out models that are already known to be exhausted globally in this run
    active_models = [m for m in MODEL_CHAIN if m not in EXHAUSTED_MODELS]
    
    # If all models are exhausted, default to the last model as a fallback safety net
    if not active_models:
        active_models = [MODEL_CHAIN[-1]]
        print(f"[WARNING] All models in chain are exhausted. Forcing retry with last resort model: {active_models[0]}")
    
    # We loop through each active model in our chain to maximize accuracy
    for model_name in active_models:
        num_keys = len(key_manager.keys)
        all_keys_quota_exhausted = True
        
        # Try all available keys for this model before falling back to the next model
        for key_attempt in range(num_keys):
            current_key = key_manager.get_current_key()
            client = None
            thai_doc = None
            english_doc = None
            try:
                client = genai.Client(api_key=current_key, http_options={'timeout': 300000})
                print(f"[EXTRACT] Trying model: {model_name} with Key #{key_manager.current_idx + 1}/{num_keys} for {filename}...")
                
                print(f"[UPLOAD] Uploading main PDF: {filename} ...")
                thai_doc = client.files.upload(file=pdf_path)
                print("   -> Main PDF upload success!")
                
                contents = [thai_doc]
                
                if en_pdf_path:
                    other_filename = os.path.basename(en_pdf_path)
                    print(f"[UPLOAD] Uploading secondary PDF for validation: {other_filename} ...")
                    english_doc = client.files.upload(file=en_pdf_path)
                    print("   -> Secondary PDF upload success!")
                    contents.append(english_doc)
                
                contents.append(prompt)
                print("   -> Waiting for Gemini processing...")
                
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0
                    )
                )
                
                # แปลง JSON ผลลัพธ์
                data = json.loads(response.text)
                
                # ตรวจสอบโครงสร้างข้อมูลเบื้องต้น
                if "series" not in data or "models" not in data:
                    raise ValueError("AI output is missing required keys ('series' or 'models')")
                
                # ตรวจสอบความสมบูรณ์ของข้อมูล
                is_valid, validation_msg = verify_extracted_data(data, lang=lang)
                if not is_valid:
                    raise ValueError(f"Data verification failed: {validation_msg}")
                
                print(f"   -> Success! Model: {model_name}, Series: '{data['series']}' ({len(data['models'])} models)")
                
                # ลบไฟล์ชั่วคราวออกจากระบบของ Google
                for doc in [thai_doc, english_doc]:
                    if doc:
                        try:
                            client.files.delete(name=doc.name)
                            print(f"   -> Temporary file {doc.name} deleted from Google server.")
                        except Exception as del_err:
                            print(f"   [WARNING] Failed to delete temporary file: {del_err}")
                    
                return data

            except Exception as e:
                error_msg = str(e)
                print(f"[ERROR] Error processing {filename} with model {model_name} (Key #{key_manager.current_idx + 1}): {error_msg}")
                
                # ลบไฟล์ชั่วคราวหากมีการสร้างขึ้นแล้ว
                for doc in [thai_doc, english_doc]:
                    if doc and client:
                        try:
                            client.files.delete(name=doc.name)
                            print(f"   -> Temporary file {doc.name} deleted from Google server.")
                        except Exception:
                            pass
                
                # ตรวจสอบว่าเป็นปัญหาจากข้อจำกัดความถี่หรือโควตา API หรือไม่
                is_rate_limit = any(term in error_msg.lower() for term in ["429", "limit", "exhausted", "quota", "503", "unavailable"])
                
                # Check if this error is specifically due to daily quota limit exhaustion (limit: 20 or limit: 0)
                is_daily_limit = False
                if is_rate_limit:
                    if any(term in error_msg.lower() for term in ["limit: 20", "limit: 0", "daily", "day", "quota exceeded"]):
                        is_daily_limit = True
                
                # If the error is NOT a daily limit (e.g. RPM limit or value/validation error), 
                # then this key still has daily quota left for this model.
                if not is_daily_limit:
                    all_keys_quota_exhausted = False
                
                # สลับ API Key เพื่อลองใหม่ในรอบถัดไป
                key_manager.rotate_key()
                
                # หน่วงเวลาก่อนลองใหม่ (หากเกิดจาก Rate Limit ให้รอนานขึ้นเป็น 20 วินาทีเพื่อให้โควตารีเซ็ตตัวเองทัน)
                sleep_time = 20 if is_rate_limit else 3
                if is_rate_limit:
                    print(f"   -> [RATE_LIMIT] Detect API quota limit. Waiting {sleep_time} seconds to cool down...")
                time.sleep(sleep_time)
                
        # If all keys returned daily limit exhaustion for this model, record it as exhausted globally
        if all_keys_quota_exhausted:
            print(f"[EXHAUSTED] Model '{model_name}' has exceeded daily limits across all keys. Adding to exhausted models.")
            EXHAUSTED_MODELS.add(model_name)
        else:
            print(f"[INFO] All keys exhausted for model {model_name} for this file. Falling back to next model in the chain...")
        
    print(f"[FATAL] Completely failed to extract {filename} using all models and keys in the pool.")
    return None

def run_batch_extraction(lang="th", target_file=None):

    if lang == "en":
        auto_folder = "bmw_brochures_auto_en"
        custom_folder = "bmw_brochures_custom_en"
        output_file = "bmw_master_specs_en.json"
        compat_file = "bmw_ai_specs_en.json"
    else:
        auto_folder = "bmw_brochures_auto"
        custom_folder = "bmw_brochures_custom"
        output_file = "bmw_master_specs.json"
        compat_file = "bmw_ai_specs.json"
    
    # สร้างโฟลเดอร์ถ้ายังไม่มี
    if not os.path.exists(auto_folder):
        os.makedirs(auto_folder)
    if not os.path.exists(custom_folder):
        os.makedirs(custom_folder)
        print(f"[INFO] Created custom brochures directory: '{custom_folder}'")
        
    # ค้นหาไฟล์ PDF ทั้งหมดในสองโฟลเดอร์
    auto_pdfs = [(auto_folder, f) for f in os.listdir(auto_folder) if f.lower().endswith(".pdf")]
    custom_pdfs = [(custom_folder, f) for f in os.listdir(custom_folder) if f.lower().endswith(".pdf")]
    
    # รวมไฟล์โดยนำ auto ก่อนแล้วตามด้วย custom (เรียงตามชื่อไฟล์ในแต่ละหมวดหมู่)
    pdf_entries = sorted(auto_pdfs, key=lambda x: x[1]) + sorted(custom_pdfs, key=lambda x: x[1])
    
    # จัดคิวเอาไฟล์ 3 รุ่นย่อยที่มีความยากที่สุดมาประมวลผลก่อนเป็นอันดับแรก
    pdf_entries = sorted(pdf_entries, key=lambda x: (0 if x[1] in THREE_MODEL_FILES else 1, x[1]))
    
    if target_file:
        # If a target file is specified, filter only that file
        pdf_entries = [entry for entry in pdf_entries if entry[1] == target_file or os.path.basename(entry[1]) == target_file]
        if not pdf_entries:
            print(f"[ERROR] Target file '{target_file}' not found in any source folders.")
            return

    if not pdf_entries:
        print(f"[WARNING] No PDF files found in '{auto_folder}' or '{custom_folder}'")
        return
        
    print(f"\n[INFO] [{lang.upper()}] Found {len(pdf_entries)} PDF files to process")
    
    master_specs = []
    processed_pdfs = set()
    
    if os.path.exists(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                master_specs = json.load(f)
                if not isinstance(master_specs, list):
                    master_specs = []
                
                # ทำความสะอาดและจับคู่คีย์ pdf_source
                for idx, item in enumerate(master_specs):
                    if "pdf_source" not in item and idx < len(pdf_entries):
                        item["pdf_source"] = pdf_entries[idx][1]
                
                # ตรวจสอบความสมบูรณ์ของข้อมูลเก่า (ข้ามถ้าเราใช้ single target file เพื่อไม่ลบข้อมูลรุ่นอื่น)
                if not target_file:
                    valid_specs = []
                    for item in master_specs:
                        is_valid, validation_msg = verify_extracted_data(item, lang=lang)
                        if is_valid:
                            valid_specs.append(item)
                        else:
                            series_name = item.get("series", "Unknown Series")
                            pdf_name = item.get("pdf_source", "Unknown PDF")
                            print(f"[CLEANUP] Discarding incomplete entry for '{series_name}' ({pdf_name}) - Reason: {validation_msg}. Will re-extract.")
                    master_specs = valid_specs
                
                processed_pdfs = {item["pdf_source"] for item in master_specs if "pdf_source" in item}
                print(f"[INFO] Loaded existing progress. Already processed: {len(processed_pdfs)} files.")
        except Exception as e:
            print(f"[WARNING] Failed to load existing '{output_file}': {e}")
            master_specs = []
            
    success_count = len(processed_pdfs)
    
    for i, (folder, filename) in enumerate(pdf_entries, 1):
        # If we specify a target file, we force extraction even if it's already in processed_pdfs
        if filename in processed_pdfs and not target_file:
            print(f"--- [{i}/{len(pdf_entries)}] Skipping (already processed): {filename} ---")
            continue
            
        pdf_path = os.path.join(folder, filename)
        print(f"\n--- [{i}/{len(pdf_entries)}] Starting: {filename} (from '{folder}') ---")
        
        # Find matching PDF
        en_pdf_path = None
        if lang == "th":
            en_pdf_path = find_matching_english_pdf(filename)
        elif lang == "en":
            en_pdf_path = find_matching_thai_pdf(filename)
            
        # Route: page-by-page for dual-PDF pairs (TH + EN), whole-PDF for TH-only
        if en_pdf_path:
            print(f"[ROUTE] Dual-PDF detected — using independent page-by-page extraction.")
            result = extract_pdf_page_by_page(pdf_path, lang=lang)
        else:
            result = extract_pdf_with_retry(pdf_path, en_pdf_path=en_pdf_path, lang=lang)
        if result:
            result["pdf_source"] = filename  # บันทึกแหล่งที่มาของไฟล์ PDF
            
            # If target_file is specified, replace the existing entry in master_specs
            if target_file:
                master_specs = [item for item in master_specs if item.get("pdf_source") != filename]
                
            master_specs.append(result)
            success_count += 1
            
            # บันทึกไฟล์ทันทีหลังสกัดสำเร็จ 1 ไฟล์
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(master_specs, f, ensure_ascii=False, indent=4)
                # บันทึกเป็นไฟล์เดี่ยวเพื่อ compatibility
                with open(compat_file, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, indent=4)
            except Exception as write_err:
                print(f"   [WARNING] Failed to write backup: {write_err}")
                
            time.sleep(2)
            
    print(f"\n[SUCCESS] [{lang.upper()}] Master specs successfully saved to '{output_file}'!")
    print(f"[SUMMARY] Successfully extracted {success_count}/{len(pdf_entries)} files")
    
    # Run the cross-database validation comparison after English batch extraction finishes
    if lang == "en":
        print("\n[BATCH] Running cross-database validation...")
        try:
            import subprocess
            import sys
            subprocess.run([sys.executable, "scratch/compare_th_en_db.py"], check=True)
        except Exception as e:
            print(f"[ERROR] Cross-database validation failed: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="BMW Specsheet Batch Extractor")
    parser.add_argument("--lang", type=str, default="th", choices=["th", "en"], help="Language of brochures to extract (th or en)")
    parser.add_argument("--file", type=str, default=None, help="Target specific PDF filename to extract")
    args = parser.parse_args()
    run_batch_extraction(lang=args.lang, target_file=args.file)