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

# Global registry to remember exhausted (Model:API_Key) combinations across the run
EXHAUSTED_COMBINATIONS = set()

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

API_KEYS = []
std_key = os.environ.get("GEMINI_API_KEY")
if std_key and not std_key.strip().endswith("_case"):
    API_KEYS.append(std_key.strip())
for idx in range(1, 11):
    key = os.environ.get(f"GEMINI_API_KEY_{idx}", "")
    if key.strip() and not key.strip().endswith("_case"):
        API_KEYS.append(key.strip())

if not API_KEYS:
    print("[ERROR] No Gemini API Keys found. Please set GEMINI_API_KEY or GEMINI_API_KEY_1/2/3.")
    sys.exit(1)

# Target Gemini model for OCR correction
MODEL_NAME = "gemini-3.6-flash"

# ─── System Prompts ───────────────────────────────────────────────────────────
PROMPT_TH = """You are an expert BMW Automotive Specification Analyst and Data Structuring Specialist.
Your task is to take a pre-extracted Markdown/HTML specification table from a BMW brochure, correct any OCR spelling mistakes (especially in Thai), and format the output into a strict JSON structure.

เป้าหมายของคุณคือ: ดึงข้อมูลสเปก "ทุกบรรทัด" และ "ทุกตัวอักษร" บนทุกหน้าของเอกสาร (รวมถึงอุปกรณ์มาตรฐานและออปชันระบบขับเคลื่อน อุปกรณ์ภายนอก อุปกรณ์ภายใน ความปลอดภัย และความบันเทิง) ห้ามตกหล่นแม้แต่ข้อเดียว เพื่อใช้เป็นข้อมูลอ้างอิงให้พนักงานขาย

กฎเหล็กที่ต้องปฏิบัติตามอย่างเคร่งครัด:
1. ห้ามสรุปความ ห้ามย่อความ ห้ามตัดออปชันย่อยทิ้งเด็ดขาด ต้องดึงข้อมูลมาแบบคำต่อคำ (Verbatim) ให้ครบทุกบรรทัดที่ปรากฏในตาราง
1.1 กฎการแก้ไขคำสะกดผิดและการคงคำศัพท์ (OCR & Terminology Strictness):
   - ให้แก้ไขเฉพาะตัวอักษร/สระที่แปรผลผิดพลาดอย่างชัดเจนเท่านั้น ห้ามปรับแต่งคำศัพท์หลักหรือคำทางเทคนิคของต้นฉบับเด็ดขาด แม้ว่าคำศัพท์เดิมจะฟังดูไม่เป็นทางการหรือขัดกับหลักไวยากรณ์สมัยใหม่
   - ห้ามเพิ่มคำหรือตัดคำออกโดยเด็ดขาด (เช่น ห้ามเปลี่ยนคำว่า "นอกห้องโดยสาร" ไปเป็น "ภายนอกห้องโดยสาร" ซึ่งถือเป็นการเพิ่มคำว่า "ภาย" เข้ามาในระบบ)
   - เมื่อพบลักษณะคำที่เกิดความผิดเพี้ยนจากการแปรผล ให้มองหาโครงสร้างคำและพยางค์ที่ใกล้เคียงเพื่อกู้คืนคำศัพท์ดั้งเดิมที่ถูกต้องของ BMW โดยคำหลักห้ามขาดหรือหายไปเด็ดขาด (เช่น หากพบคำว่า "โทรศอก" ให้แก้ไขเป็น "โทรออก" เพื่อรักษาคำศัพท์ดั้งเดิมว่า "ปุ่มโทรออกฉุกเฉิน" ห้ามตัดคำว่า "ออก" ทิ้งเหลือเพียง "ปุ่มโทรฉุกเฉิน")
2. ในเอกสารจะมีตารางอุปกรณ์มาตรฐาน (เช่น ระบบขับเคลื่อน อุปกรณ์ภายนอก อุปกรณ์ภายใน ความปลอดภัย ความบันเทิง) บนหน้ากลางๆ (หน้า 2, 3, 4) คุณต้องดึงข้อมูลเหล่านี้มาให้ครบถ้วน ห้ามข้ามเด็ดขาด
3. **การจัดการช่องว่าง (Blank Cells):**
   - หากช่องใดในตารางเป็นช่องว่างเปล่า หรือระบุเครื่องหมายขีด "-" ให้ระบุเป็น "-" เสมอ ห้ามคาดเดาหรือพยายามเติมสัญลักษณ์เองเด็ดขาด โค้ด Python จะจัดการกู้คืนสเปกมาตรฐานเองในภายหลัง
   - หากช่องระบุสัญลักษณ์/ตัวอักษรใดๆ ที่แสดงถึงการมีอยู่ของออปชัน (เช่น "■", "□", "•", "L", "S", หรือตัวเลขเชิงอรรถ "1", "2") ให้ดึงเป็น "■" (มีติดตั้ง)
4. หากออปชันไหนระบุรายละเอียดที่แตกต่างกันในแต่ละรุ่นย่อย ให้ใส่รายละเอียดนั้นลงไปให้ตรงรุ่น
5. **(สำคัญมาก) สำหรับหมวดสีตัวถังและวัสดุภายใน (Paintwork & Upholstery):** ในโบรชัวร์จะเป็นตาราง Matrix จับคู่ระหว่างสีตัวถังภายนอก (แถว/Row) และสีเบาะ/วัสดุหนังภายใน (คอลัมน์/Column) โดยมีเครื่องหมายสี่เหลี่ยม (■ หรือ □) แสดงการจับคู่ ให้คุณสกัดข้อมูลดังนี้:
   - คุณต้องระบุรุ่นย่อยของรถให้ตรงกับตาราง (เช่น 740d M Sport, 750e xDrive M Sport, 320d M Sport เป็นต้น)
   - **การสกัดชื่อวัสดุเบาะหนังภายใน:** ในหัวคอลัมน์ของตาราง Upholstery มักจะมีแถวซ้อนกัน โดยแถวบนสุดจะระบุชนิดของหนังเบาะ (เช่น BMW Individual leather 'Merino', Vernasca leather, Sensatec perforated, Leather 'Veganza') และแถวถัดลงมาจะระบุสีเบาะหรือคำขยายย่อย (เช่น Black, Mocha, Veganza perforated | Coral Red/Black)
   - **(สำคัญที่สุด) คุณต้องระบุชนิดหนังเบาะควบคู่กับสีเบาะเสมอ** โดยเขียนให้อยู่ในรูปแบบ `"ชนิดหนัง - สีเบาะ"` เช่น `"BMW Individual leather 'Merino' - Mocha"` หรือ `"Vernasca leather - Black"`
   - **(สำคัญมาก) หากหัวคอลัมน์ Upholstery มีแถวซ้อนกันหลายชั้น** (เช่น แถวบนเขียนว่า `Leather 'Veganza'` และแถวล่างคือ `Veganza perforated | Coral Red/Black`) **คุณต้องดึงข้อความจากหัวตารางทุกชั้นมาเชื่อมโยงกันเสมอ ห้ามตัดข้อความแถวบนสุดทิ้งเด็ดขาด** ให้ระบุในรูปแบบเชื่อมต่อ เช่น `"Leather 'Veganza' - Veganza perforated | Coral Red/Black"` หรือ `"BMW Individual leather 'Merino' - Black"`
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
   - **การตรวจสอบเส้นตารางแบ่งแถว (Horizontal Grid Lines):** ให้สังเกตเส้นตารางแนวนอนที่เป็นตัวแบ่งแถวเป็นหลัก หากไม่มีเส้นตารางคั่นระหว่างบรรทัดข้อความเหล่านั้น ให้ถือว่าเป็นช่องตารางแถวเดียวกันและต้องนำข้อความทั้งหมดมารวมกันเป็นหัวข้อเดียวใน JSON เสมอ ห้ามแยกเป็นคนละแถวโดยเด็ดขาด (ตัวอย่างเช่น ข้อความ Carbon Fibre, ถักด้วยวัสดุสีเงินแบบ M, และ คอนโซลกลางสีดำเงาแบบ Piano Finish Black ที่เรียงต่อกันโดยไม่มีเส้นคั่น ต้องรวมเป็นแถวเดียว)
   - **การตรวจสอบเครื่องหมายคู่ตาราง:** ให้ระมัดระวังเป็นพิเศษหากสัญลักษณ์สี่เหลี่ยมดำ (■) ถูกพิมพ์อยู่เยื้องลงมาในระดับบรรทัดที่สอง (เช่น ตรงกับคำว่า 'Diamond') คุณต้องจับคู่สัญลักษณ์นี้เข้ากับหัวข้อหลักนั้น ห้ามนำไปสับสนหรือคิดว่าเป็นสัญลักษณ์ของแถวบน (เช่น Harman Kardon) หรือแถวล่างเด็ดขาด
   - **ห้ามลอกเลียนแบบหรือใส่เครื่องหมายในช่องว่าง:** หากช่องใดในตารางเป็นช่องว่างเปล่า (ไม่มีเครื่องหมาย ■) ให้ระบุเป็น "-" เท่านั้น ห้ามนำสัญลักษณ์ (■) จากแถวอื่นที่อยู่ใกล้เคียงมาใส่เด็ดขาด ตัวอย่างเช่น ในรุ่น **BMW XM (XM 50e และ XM 50e (Shadow Line))**:
     * แถว 'ระบบเครื่องเสียงรอบทิศทาง Harman Kardon' มีเครื่องหมาย (■) เฉพาะในคอลัมน์ที่ 1 (XM 50e) เท่านั้น ส่วนคอลัมน์ที่ 2 (XM 50e (Shadow Line)) เป็นช่องว่างเปล่า คุณต้องระบุรุ่นแรกเป็น "■" และรุ่นที่สองเป็น "-" เท่านั้น
     * แถว 'ระบบเสียงรอบทิศทางคุณภาพสูง Bowers & Wilkins Diamond' มีเครื่องหมาย (■) เฉพาะในคอลัมน์ที่ 2 (XM 50e (Shadow Line)) เท่านั้น ส่วนคอลัมน์ที่ 1 (XM 50e) เป็นช่องว่างเปล่า คุณต้องระบุรุ่นแรกเป็น "-" และรุ่นที่สองเป็น "■" เท่านั้น ห้ามตอบว่ารุ่นที่สองมีระบบเครื่องเสียงทั้งสองระบบเด็ดขาด
7. **(สำคัญมาก) ข้อมูลเอกสารอ้างอิงและเชิงอรรถ:**
   - ห้ามดึงข้อมูลท้ายกระดาษ (Footer) เช่น วันที่พิมพ์ หรือ รหัสแพ็กเกจ (Z...) มาสร้างหมวดหมู่เองเด็ดขาด โค้ด Python จะจัดการดึงข้อมูลส่วนนี้โดยตรงจาก PDF เอง
   - หากในตารางหรือท้ายตารางมีข้อความที่เป็นเชิงอรรถ/คำอธิบายเพิ่มเติมกำกับด้วยตัวเลข (เช่น "1 ...", "2 ...", หรือ "* ...") คุณต้องดึงหมายเหตุและเชิงอรรถเหล่านี้ทั้งหมดมาจัดทำเป็นหมวดหมู่ใหม่ชื่อว่า `"หมายเหตุ"` โดยตั้งชื่อหัวข้อรายละเอียด (Topic) เป็นข้อความอธิบายนั้นทั้งบรรทัด และให้ค่าสเปก (Value) เป็น `"-"` เสมอ
8. **(สำคัญมาก) ห้ามรวมหรือยุบหมวดหมู่:** ห้ามนำรายละเอียดออปชันของหมวดหมู่หนึ่งไปรวมเข้ากับอีกหมวดหมู่หนึ่งเด็ดขาด (เช่น ห้ามนำออปชันของ อุปกรณ์ภายนอก หรือ อุปกรณ์ภายใน ไปใส่รวมไว้ใต้หมวดหมู่ ความปลอดภัย) ต้องสร้างคีย์ category แยกสำหรับแต่ละหมวดหมู่ให้ครบถ้วนในผลลัพธ์ JSON
    - คำศัพท์เช่น "ชุดตกแต่งพิเศษ", "Line / package", "Line / Package" หรือคำอื่นๆ ที่ระบุถึงแพ็กเกจการตกแต่ง ให้ถือเป็นหัวข้อหมวดหมู่ (Category) เสมอ ห้ามยุบไปรวมกับหมวดหมู่อื่นเด็ดขาด
    - ทุกๆ หัวข้อหมวดหมู่ที่ตรวจพบ จะต้องมีออปชันย่อย (details) บันทึกอยู่ภายใต้หมวดหมู้นั้นๆ เสมอ
    - ทุกๆ ข้อความที่อยู่ในเอกสาร (หรือที่สแกนหลุดออกมานอกตาราง) ที่ไม่ใช่หัวกระดาษ (Header) หรือท้ายกระดาษ (Footer) ให้ถือว่าเป็นออปชันย่อย (Topic) และต้องถูกสกัดเข้ามาใน JSON ห้ามข้ามหรือละทิ้งเด็ดขาด
9. **(สำคัญมาก) ข้อมูลการชาร์จรถยนต์ไฟฟ้า (AC / DC Charging):** สกัดข้อมูลการชาร์จไฟหรือระยะเวลาชาร์จแบบต่างๆ แบ่งแยกออกเป็น 4 หมวดหมู่ย่อยดังนี้เฉพาะเมื่อปรากฏตารางข้อมูลการชาร์จในโบรชัวร์เท่านั้น (ห้ามสร้างขึ้นมาหากไม่มีข้อมูล):
   - "การชาร์จแบบกระแสสลับ (AC)" สำหรับกำลังไฟชาร์จ AC สูงสุด
   - "ระยะเวลาในการชาร์จจาก 0 - 100%" สำหรับระยะเวลาและตัวเลือกชาร์จ AC ทั้งหมด
   - "การชาร์จแบบกระแสตรง (DC)" สำหรับกำลังไฟชาร์จ DC สูงสุด
   - "ระยะเวลาในการชาร์จจาก 10 - 80%" สำหรับระยะเวลาและตัวเลือกชาร์จ DC ทั้งหมด
10. **(สำคัญมาก) การกำหนดชื่อซีรีส์ (Series Name):**
    - ดึงชื่อซีรีส์ (series) จากหัวเอกสารของโบรชัวร์ตามปกติ (เช่น "BMW 3 SERIES" หรือ "BMW 5 SERIES") Python จะเป็นผู้จัดกลุ่มซีรีส์ตระกูลไฟฟ้า "i" หรือตระกูลสมรรถนะสูง "M" โดยอัตโนมัติ
11. **(สำคัญมาก) สำหรับตารางสเปกชีตที่มีเพียงรุ่นย่อยเดียว (มีคอลัมน์รุ่นรถคอลัมน์เดียว):**
    - ให้ถือว่าทุกหัวข้อออปชันที่ปรากฏในตารางของเอกสารเล่มนั้นมีติดตั้งเป็นมาตรฐาน (ระบุค่าเป็น "■" เสมอ) ห้ามระบุค่าเป็น "-" โดยเด็ดขาด
    - ยกเว้นกรณีที่ช่องข้อมูลระบุค่าเป็นข้อความรายละเอียดเชิงเทคนิคเฉพาะเจาะจง (เช่น ตัวเลขแรงม้า, ขนาดมิติต่างๆ, ชื่อสีเบาะ หรือคำอธิบาย) ให้ใส่ตามค่าข้อความจริงนั้น
12. **กฎการจัดวางตำแหน่งตัวเลขเชิงอรรถ (Footnote Placement Rule):** ตัวเลขเชิงอรรถ (เช่น `¹`, `²`, `³` หรือตัวยกใดๆ) จะปรากฏต่อท้ายชื่อข้อกำหนดหรือออปชันในช่องตารางฝั่งซ้าย (Topic) เท่านั้น ห้ามนำตัวเลขเชิงอรรถเหล่านี้ไปใส่ร่วมกับข้อมูลในช่องตารางฝั่งขวาที่เป็นรายละเอียดหรือค่าสเปก (Value) โดยเด็ดขาด (ตัวอย่างเช่น ฝั่งซ้าย Topic = "ความเร็วสูงสุด (กิโลเมตร/ชั่วโมง)¹", ฝั่งขวา Value = "300" เท่านั้น ห้ามเขียนฝั่งขวาเป็น "300¹")

หมวดหมู่หลักที่ต้องปรากฏใน JSON เสมอ (ห้ามตกหล่น):
- เครื่องยนต์และสมรรถนะ
- อัตราสิ้นเปลืองน้ำมันเชื้อเพลิง และระดับการปล่อย CO2
- ล้อและยาง
- มิติรถยนต์
- ระบบขับเคลื่อนและเทคโนโลยี
- อุปกรณ์ภายนอก
- อุปกรณ์ภายใน
- ระบบความบันเทิงและการสื่อสาร (ระมัดระวังความถูกต้องของเครื่องเสียง Harman Kardon และ Bowers & Wilkins Diamond ในรุ่นย่อยต่างๆ ห้ามคัดลอกเครื่องหมายไปยังรุ่นที่ไม่มีโดยเด็ดขาด)
- ความปลอดภัย

หมวดหมู่เฉพาะกิจ (สร้างขึ้นเฉพาะเมื่อมีข้อมูลตารางระบุในโบรชัวร์เท่านั้น ห้ามสร้างเป็นค่าว่าง):
- Paintwork / สีตัวถังและวัสดุภายใน (เฉพาะรุ่นที่มีตารางแสดงการจับคู่สีตัวถังกับเบาะภายใน)
- การชาร์จแบบกระแสสลับ (AC) / ระยะเวลาในการชาร์จจาก 0 - 100% (เฉพาะรุ่นที่มีข้อมูลการชาร์จไฟ)
- การชาร์จแบบกระแสตรง (DC) / ระยะเวลาในการชาร์จจาก 10 - 80% (เฉพาะรุ่นที่มีข้อมูลการชาร์จไฟ)

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
3. **Blank Cells Handling:**
   - If a cell contains an explicit dash "-" or "No", specify "-" (absent).
   - If a cell is blank/empty "" in the Markdown table, specify "-" only. Do not guess or copy checkmarks from adjacent rows or columns. Python post-processing will recover the standard safety and technological features later.
   - If a cell contains a footnote number (like "1", "2") or symbols like "■", "□", "•", "L", "S" that indicate option presence, map it as present "■".
4. If an option specifies different details for each model, put the corresponding detail under each model.
5. **(Very Important) Paintwork & Upholstery Matrix:** In the brochure, there will be a matrix table indicating the combination of exterior paintwork (row) and interior upholstery/leather type (column). You must extract the data using these steps:
   - Identify the model name for each specific table (e.g., 740d M Sport, 320d M Sport, etc.).
   - **Extract Upholstery with Leather Type:** The column headers for Upholstery typically have nested rows where the top row indicates the leather/material type (e.g., "BMW Individual leather 'Merino'", "Vernasca leather") and the bottom row indicates the color (e.g., "Black", "Mocha").
   - **(Critical) You MUST always prefix the leather type to the upholstery color** in the format `"Leather Type - Color Name"`. Example values: `"BMW Individual leather 'Merino' - Mocha"`, `"Vernasca leather - Black"`.
   - **(Critical) If the Upholstery column headers have multiple nested rows,** you must concatenate all header levels together. Never omit the top-most leather type. Example: `"Leather 'Veganza' - Veganza perforated | Coral Red/Black"`.
   - For each row (Paintwork / Paint color):
     1. Scan horizontally across the columns to locate the option indicators (such as ■, □, or any footnote numbers/marks).
     2. Trace vertically to find which upholstery column the symbol aligns with.
     3. Put the full upholstery descriptor (including leather type and color name) in the value field.
     4. If there are multiple matching combinations, join them with a comma (e.g., `"BMW Individual leather 'Merino' - Mocha, BMW Individual leather 'Merino' - Black"`).
     5. If a row has no symbol in any column, specify "-". Do not just write "Yes" or skip the row.
6. **(Very Important) Multi-line row labels in standard equipment and specification tables:**
   - If a row topic is long and wraps onto a second line, join them into a single topic in your JSON output.
   - **Checking row grid lines:** Look at the horizontal grid lines (divider lines) in the table. If there are no horizontal divider lines separating lines of text, they belong to the SAME cell/row and must be joined into a single topic. Do not split them. (e.g. if 'Carbon Fibre...', 'with silver stitching...', and 'Piano Finish Black' are listed together without horizontal divider lines between them, they must be combined into one single topic).
   - **Aligning option symbols:** Pay extra attention if the black square symbol (■) is vertically placed on the second line of the wrapped text. You must correctly associate this symbol with the joined row topic.
   - **Never copy symbols to blank cells:** If a cell is blank (no symbol) for a model, specify "-". Do not copy symbols (■) from adjacent rows or columns.
7. **(Very Important) Footer Information and Footnotes:**
   - Do NOT attempt to extract page footers, publication dates, print dates, or local package codes. Python post-processing will extract this metadata directly from the PDF.
   - If pages contain numbered or asterisked footnotes at the bottom (e.g. "1 ...", "2 ...", or "* ..."), you must extract all of these footnotes/notes into a dedicated category named `"Notes"` with the full explanatory text as the topic name, and set the value to `"-"` for all models.
8. **(Very Important) Do not merge categories:** Do not combine options of one category into another. You must create a separate category key for each group of specifications in the JSON output.
     - Terms like "Line / package", "Line / Package", or similar words representing trim packages must always be treated as Category headers. Never merge them into other categories.
     - Every category header detected must contain its respective sub-options (details) under it.
     - Every text in the document that is not page headers or footers must be treated as a sub-option (Topic) and must be extracted into the JSON. Never skip or omit them.
9. **(Very Important) Electric Vehicle Charging Specs (AC / DC Charging):** Extract charging specifications into the following 4 categories only when a charging specification table is present in the brochure (do not create them if no charging data exists):
   - "AC CHARGING" for maximum AC charging power
   - "CHARGING TIME 0 - 100%" for AC charging times and options
   - "DC CHARGING" for maximum DC charging power
   - "CHARGING TIME 10 - 80%" for DC charging times and options
10. **(Very Important) Series Name:**
    - Extract the series name (series) from the brochure header as normal (e.g., "BMW 3 SERIES" or "BMW 5 SERIES"). Python post-processing will automatically handle the electric "i" family and performance "M" family series naming grouping.

Standard Categories (Must always appear in JSON):
- Engine and Performance
- Fuel Consumption and CO2 Emission
- Wheels and Tyres
- Dimension
- Drivetrain and Technology
- Exterior Equipment
- Interior Equipment
- Entertainment and Communication
- Safety

Conditional Categories (Extract ONLY if data table is present in the brochure; DO NOT create empty placeholders):
- Paintwork & Upholstery (Only if the color-upholstery combination matrix is present)
- AC CHARGING / CHARGING TIME 0 - 100% (Only for EV/PHEV models with charging tables)
- DC CHARGING / CHARGING TIME 10 - 80% (Only for EV/PHEV models with charging tables)

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
                if "พิม" in line_s or "Printed on" in line_s or "Effective from" in line_s or "Publication" in line_s or ("(" in line_s and ")" in line_s and "Z" in line_s):
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
                            

    # Apply single variant auto recovery if there is only 1 model variant in the document
    if len(merged.get("models", [])) == 1:
        model_data = merged["models"][0]
        for spec in model_data.get("specifications", []):
            cat_name = spec.get("category", "")
            # Skip non-option categories and paintwork matrices
            if cat_name in ("ข้อมูลเอกสารอ้างอิง", "มิติรถยนต์", "เครื่องยนต์และสมรรถนะ", 
                            "อัตราสิ้นเปลืองน้ำมันเชื้อเพลิง และระดับการปล่อย CO2",
                            "การชาร์จแบบกระแสสลับ (AC)", "ระยะเวลาในการชาร์จจาก 0 - 100%",
                            "การชาร์จแบบกระแสตรง (DC)", "ระยะเวลาในการชาร์จจาก 10 - 80%") or \
               "Paintwork" in cat_name or "สีตัวถัง" in cat_name or "Upholstery" in cat_name:
                continue
            for detail in spec.get("details", []):
                if str(detail.get("value", "")).strip() in ("-", "", "None"):
                    detail["value"] = "■"

    return merged

# ─── Pipeline Orchestrator ────────────────────────────────────────────────────
def post_process_extracted_json(merged_output: dict, pdf_path: str, lang_code: str = "th") -> dict:
    """
    Applies the Python deconstruction post-processing rules to the extracted JSON object:
    1. Removes footnote superscript digits from values using regex.
    2. Groups and overrides the root-level 'series' name if any model is in 'i' or 'M' family.
    3. Recovers blank cells for standard safety and tech features.
    4. Extracts print date and package codes from page footers using pypdf and inserts the Document References category.
    """
    import re
    
    # --- 1. Footnote Removal from Values ---
    # Superscript characters to remove: ¹, ², ³, ⁴, ⁵, ⁶, ⁷, ⁸, ⁹, ⁰
    superscript_re = re.compile(r'[\u00b9\u00b2\u00b3\u2070\u2074-\u2079]')
    
    for model in merged_output.get("models", []):
        for spec in model.get("specifications", []):
            for detail in spec.get("details", []):
                val = detail.get("value")
                if isinstance(val, str):
                    cleaned_val = superscript_re.sub('', val).strip()
                    detail["value"] = cleaned_val

    # --- 2. Series Grouping & Naming ---
    model_names = [m.get("model_name", "").strip() for m in merged_output.get("models", [])]
    orig_series = merged_output.get("series", "").strip()
    
    new_series = orig_series
    for mname in model_names:
        # i-family: check if starts with 'i' followed by letter/digit (e.g. i5, iX1)
        if re.match(r'^i[0-9a-zA-Z]', mname):
            first_word = mname.split()[0]
            new_series = f"BMW {first_word}"
            break
        # M-family: starts with M followed by a single digit (like M2, M3, M4, M5, M8), or starts with XM
        elif re.match(r'^M[23458](\s|$|[a-zA-Z])', mname) and not re.match(r'^M\d{3}', mname):
            # Pure M family
            m = re.match(r'^M\d', mname.split()[0])
            if m:
                new_series = f"BMW {m.group(0)}"
                break
        elif mname.startswith("XM"):
            new_series = "BMW XM"
            break
            
    merged_output["series"] = new_series

    # --- 3. Blank Cell Recovery for Standard Safety/Tech ---
    # Standard safety and tech keywords (lowercase)
    safety_keywords = [
        "airbag", "ถุงลม",
        "abs", "anti-lock", "ป้องกันล้อล็อก",
        "dsc", "dynamic stability control", "ควบคุมเสถียรภาพ",
        "isofix", "child seat mounting", "ยึดเบาะนั่งสำหรับเด็ก", "จุดยึดเบาะนั่ง",
        "brake assist", "เสริมแรงเบรก",
        "alarm", "สัญญาณเตือนภัย",
        "teleservices", "teleservice",
        "emergency call", "โทรออกฉุกเฉิน",
        "comfort access", "สะดวกสบายในการเข้า", "เข้าออกห้องโดยสาร"
    ]
    
    for model in merged_output.get("models", []):
        for spec in model.get("specifications", []):
            for detail in spec.get("details", []):
                val = str(detail.get("value", "")).strip()
                topic = str(detail.get("topic", "")).lower()
                if val in ("", "-", "None", "none"):
                    if any(kw in topic for kw in safety_keywords):
                        detail["value"] = "■"

    # --- 4. Document References Footers Extraction (pypdf) ---
    footer_text = extract_pdf_footer_text(pdf_path)
    pub_date = "-"
    pack_codes = []
    
    # Process lines in footer_text to find date and package codes
    for line in footer_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        
        # Extract publication date
        if "Effective from" in line or "Printed on" in line or "พิม" in line or "วันที่" in line:
            parts = line.split("|")
            date_part = parts[0].strip()
            date_part = re.sub(r'^(Effective from|Printed on|พิมพ์วันที่|พิมพวันที่|พิมพ์|พิมพ|วันที่)\s*', '', date_part)
            pub_date = date_part.strip()
            
        # Find all occurrences of parentheses containing a capital Z followed by characters
        matches = re.findall(r'\([^)]*\)', line)
        for m in matches:
            if "Z" in m and m not in pack_codes:
                pack_codes.append(m.strip())
                
    num_models = len(merged_output.get("models", []))
    while len(pack_codes) < num_models:
        pack_codes.append("-")
    pack_codes = pack_codes[:num_models]
    
    # Remove any existing Document References categories
    cat_to_remove = "ข้อมูลเอกสารอ้างอิง" if lang_code == "th" else "Document References"
    topic_date = "วันที่พิมพ์เอกสาร" if lang_code == "th" else "Publication Date"
    topic_pack = "รหัสแพ็กเกจ (Local Pack)" if lang_code == "th" else "Package Code (Local Pack)"
    
    for idx, model in enumerate(merged_output.get("models", [])):
        # Filter out existing category if any
        model["specifications"] = [
            spec for spec in model.get("specifications", [])
            if spec.get("category", "").strip().lower() != cat_to_remove.lower()
        ]
        
        # Create new category
        new_cat = {
            "category": cat_to_remove,
            "details": [
                {"topic": topic_date, "value": pub_date},
                {"topic": topic_pack, "value": pack_codes[idx]}
            ]
        }
        model["specifications"].append(new_cat)
        
    return merged_output


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
            if not MINERU_API_TOKEN or MINERU_API_TOKEN == "mock_token":
                raise ValueError("No MinerU API Token provided. Forcing direct PDF extraction.")
            md_content = parse_pdf_via_api(pdf_path, lang_code)
            print("[MINERU] Successfully retrieved Markdown content.")
            # Save a temporary copy of the markdown content for inspection/debugging
            with open(md_debug_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            print(f"[DEBUG] Saved raw Markdown to: {md_debug_path}")
        except Exception as e:
            print(f"[MINERU WARNING] MinerU extraction failed or bypassed: {e}")
            print("[FALLBACK] Using Direct PDF Extraction via Gemini Multimodal API...")
            
            system_prompt = PROMPT_TH if lang_code == "th" else PROMPT_EN
            
            # Extract PDF footer metadata directly using pypdf
            footer_text = extract_pdf_footer_text(pdf_path)
            
            success_direct = False
            key_idx = 0
            model_pool = [MODEL_NAME, "gemini-3.5-flash", "gemini-3.6-flash-lite", "gemini-3.5-flash-lite"]
            model_idx = 0
            attempts = 0
            max_attempts = len(API_KEYS) * len(model_pool) * 2
            
            while not success_direct and attempts < max_attempts and len(API_KEYS) > 0:
                current_model = model_pool[model_idx]
                key = API_KEYS[key_idx]
                combo = f"{current_model}:{key}"
                
                if combo in EXHAUSTED_COMBINATIONS:
                    key_idx = (key_idx + 1) % len(API_KEYS)
                    if key_idx == 0:
                        model_idx = (model_idx + 1) % len(model_pool)
                    attempts += 1
                    continue
                
                attempts += 1
                try:
                    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=120000))
                    print(f"      [DIRECT] Uploading PDF '{pdf_path}' to Gemini File API for key #{key_idx+1}...")
                    pdf_ref = client.files.upload(file=pdf_path)
                    
                    prompt = f"{system_prompt}\n\nYour task is to parse the ENTIRE attached PDF brochure into the strict JSON format."
                    if footer_text:
                        prompt += f"\n\nHere is the footer metadata from the document page:\n{footer_text}"
                    
                    print(f"      [DIRECT] Calling Gemini model {current_model}...")
                    response = client.models.generate_content(
                        model=current_model,
                        contents=[pdf_ref, prompt],
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json"
                        )
                    )
                    
                    merged_output = json.loads(response.text)
                    if isinstance(merged_output, list) and len(merged_output) > 0:
                        merged_output = merged_output[0]
                    
                    # Clean up file
                    try:
                        client.files.delete(name=pdf_ref.name)
                    except:
                        pass
                        
                    # Save final structured specsheet
                    merged_output["source_file"] = os.path.basename(pdf_path)
                    merged_output["pdf_source"] = os.path.basename(pdf_path)
                    merged_output["extracted_by_models"] = [current_model]
                    
                    # Run Python post-processing
                    merged_output = post_process_extracted_json(merged_output, pdf_path, lang_code)
                    
                    # Apply overrides
                    try:
                        from manual_override_manager import apply_overrides
                        pdf_basename = os.path.basename(pdf_path)
                        for m in merged_output.get("models", []):
                            apply_overrides(pdf_basename, m)
                    except Exception as oe:
                        print(f"[WARNING] Overrides failed: {oe}")
                        
                    print(f"[SAVE] Saving JSON to: {output_json_path}")
                    with open(output_json_path, "w", encoding="utf-8") as f:
                        json.dump(merged_output, f, ensure_ascii=False, indent=4)
                    print("[COMPLETE] Direct PDF extraction finished successfully!")
                    return
                    
                except Exception as ex:
                    print(f"      [WARNING] Direct extraction failed on key #{key_idx+1} with model {current_model}: {ex}")
                    EXHAUSTED_COMBINATIONS.add(combo)
                    key_idx = (key_idx + 1) % len(API_KEYS)
                    if key_idx == 0:
                        model_idx = (model_idx + 1) % len(model_pool)
            
            print("[FATAL] All keys/models failed for Direct PDF extraction.")
            sys.exit(1)
            
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
    models_used = []
    key_idx = 0
    model_pool = [MODEL_NAME, "gemini-3.5-flash", "gemini-3.6-flash-lite", "gemini-3.5-flash-lite"]
    model_idx = 0
    
    uploaded_files = {}
    try:
        for i, seg in enumerate(segments):
            print(f"   [API] Processing segment {i+1}/{len(segments)} via Gemini...")
            
            success = False
            attempts = 0
            max_attempts = len(API_KEYS) * len(model_pool) * 2  # Allow multiple retries per key/model combination
            
            prompt = f"{system_prompt}\n\nHere is the input table segment:\n\n{seg}"
            if footer_text:
                prompt += f"\n\nHere is the footer metadata from the document page:\n{footer_text}"
                
            keys_tried_for_current_model = 0
            
            while not success and attempts < max_attempts and len(API_KEYS) > 0:
                current_model = model_pool[model_idx]
                key = API_KEYS[key_idx]
                combo = f"{current_model}:{key}"
                
                if combo in EXHAUSTED_COMBINATIONS:
                    keys_tried_for_current_model += 1
                    if keys_tried_for_current_model >= len(API_KEYS):
                        model_idx = (model_idx + 1) % len(model_pool)
                        keys_tried_for_current_model = 0
                        print(f"      [MODEL-FALLBACK] All keys exhausted for {current_model}. Rotated to model: {model_pool[model_idx]}")
                    else:
                        key_idx = (key_idx + 1) % len(API_KEYS)
                    attempts += 1
                    continue
                
                attempts += 1
                if attempts > 1:
                    print(f"      [RETRY] Attempt {attempts} using model={current_model}...")
                    
                try:
                    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=60000))
                    
                    # Upload PDF once per key
                    if key not in uploaded_files:
                        print(f"      [HYBRID] Uploading PDF to Gemini File API for Key #{key_idx+1}...")
                        uploaded_files[key] = client.files.upload(file=pdf_path)
                        
                    pdf_ref = uploaded_files[key]
                    
                    response = client.models.generate_content(
                        model=current_model,
                        contents=[pdf_ref, prompt],
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json"
                        )
                    )
                    segment_json = json.loads(response.text)
                    if isinstance(segment_json, list) and len(segment_json) > 0 and isinstance(segment_json[0], dict):
                        segment_json = segment_json[0]
                    extracted_segments.append(segment_json)
                    if current_model not in models_used:
                        models_used.append(current_model)
                    print(f"      -> Segment {i+1} OCR Correction OK.")
                    success = True
                except Exception as e:
                    err_msg = str(e)
                    print(f"      [WARNING] Gemini Error on Key #{key_idx+1} ({current_model}): {e}")
                    
                    is_rate_limit = any(term in err_msg.lower() for term in [
                        "resource_exhausted", "quota", "rate limit", "rate_limit", "unavailable", "demand", "deadline", "timeout"
                    ])
                    is_invalid_key = any(term in err_msg for term in ["API key not valid", "API_KEY_INVALID", "INVALID_ARGUMENT"])
                    
                    if is_rate_limit:
                        if "requestsperday" in err_msg.lower():
                            EXHAUSTED_COMBINATIONS.add(combo)
                            print(f"      [GDRIVE/QUOTA] Marked {current_model} on Key #{key_idx+1} as exhausted for this run (Daily Limit).")
                            keys_tried_for_current_model += 1
                        else:
                            # Temporary RPM limit - sleep and rotate key but do not ban and do not increment tried keys count
                            import re
                            match = re.search(r"Please retry in ([\d\.]+)s", err_msg)
                            delay = float(match.group(1)) if match else 10.0
                            print(f"      [COOLDOWN] Temporary rate limit hit. Sleeping {delay:.1f}s...")
                            time.sleep(delay + 1.0)
                        
                        if keys_tried_for_current_model >= len(API_KEYS):
                            model_idx = (model_idx + 1) % len(model_pool)
                            key_idx = (key_idx + 1) % len(API_KEYS)
                            keys_tried_for_current_model = 0
                            print(f"      [MODEL-FALLBACK] All keys failed for {current_model}. Rotated to model: {model_pool[model_idx]}")
                        else:
                            key_idx = (key_idx + 1) % len(API_KEYS)
                            print(f"      [ROTATE] Rotated to Key #{key_idx+1} for model {current_model}.")
                            
                    elif is_invalid_key:
                        print(f"      [REMOVE] Removing invalid API Key #{key_idx+1} from pool.")
                        API_KEYS.pop(key_idx)
                        if not API_KEYS:
                            print("[FATAL] All Gemini keys in pool have been removed as invalid.")
                            sys.exit(1)
                        key_idx = key_idx % len(API_KEYS)
                        keys_tried_for_current_model = 0
                        
                    else:
                        keys_tried_for_current_model += 1
                        if keys_tried_for_current_model >= len(API_KEYS):
                            model_idx = (model_idx + 1) % len(model_pool)
                            key_idx = (key_idx + 1) % len(API_KEYS)
                            keys_tried_for_current_model = 0
                            print(f"      [MODEL-FALLBACK] General errors on all keys for {current_model}. Rotated to model: {model_pool[model_idx]}")
                        else:
                            key_idx = (key_idx + 1) % len(API_KEYS)
                            print(f"      [ROTATE] Rotated to Key #{key_idx+1} for model {current_model}.")
                            
            if not success:
                print(f"[FATAL] All Gemini keys/models failed to extract segment {i+1}.")
                sys.exit(1)
    finally:
        # Clean up all uploaded files
        for k, f_ref in uploaded_files.items():
            try:
                print(f"   [HYBRID] Cleaning up uploaded file '{f_ref.name}'...")
                cleanup_client = genai.Client(api_key=k)
                cleanup_client.files.delete(name=f_ref.name)
            except Exception as e:
                print(f"   [HYBRID WARNING] Failed to clean up file '{f_ref.name}': {e}")
            
    # Step 4: Merge segments into a single unified JSON
    print("[MERGE] Merging segment JSONs...")
    merged_output = merge_spec_json_list(extracted_segments)
    # Add source file metadata to prevent merging with different PDF files
    merged_output["source_file"] = os.path.basename(pdf_path)
    merged_output["pdf_source"] = os.path.basename(pdf_path)
    merged_output["extracted_by_models"] = models_used
    
    # Run Python post-processing
    merged_output = post_process_extracted_json(merged_output, pdf_path, lang_code)
    
    # Apply Manual Overrides
    try:
        from manual_override_manager import apply_overrides
        pdf_basename = os.path.basename(pdf_path)
        for model in merged_output.get("models", []):
            apply_overrides(pdf_basename, model)
    except Exception as oe:
        print(f"[WARNING] Failed to apply manual overrides: {oe}")
        
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
