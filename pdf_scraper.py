import os
import sys
import time
from urllib.parse import unquote
from playwright.sync_api import sync_playwright

# Fix Windows console encoding issues for Thai/Emoji characters
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Configurations for both Thai and English brochures
TARGETS = [
    {
        "lang": "th",
        "url": "https://www.bmw.co.th/th/topics/brochure.html",
        "download_dir": "bmw_brochures_auto"
    },
    {
        "lang": "en",
        "url": "https://www.bmw.co.th/en/topics/brochure.html",
        "download_dir": "bmw_brochures_auto_en"
    }
]

def download_pdf(page, pdf_url, download_dir, filename):
    """ฟังก์ชันดาวน์โหลดไฟล์โดยใช้ Session ของ Playwright"""
    try:
        response = page.request.get(pdf_url, timeout=30000)
        if response.ok:
            with open(os.path.join(download_dir, filename), 'wb') as f:
                f.write(response.body())
            return True
        else:
            print(f"   -> [Error] Server return HTTP {response.status}")
    except Exception as e:
        print(f"   -> [Error] {e}")
    return False

all_web_filenames = set()

def scrape_target(target):
    global all_web_filenames
    lang = target["lang"]
    url = target["url"]
    download_dir = target["download_dir"]

    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    print(f"\n==================================================")
    print(f"กำลังเริ่มซิงค์ข้อมูลภาษา: {lang.upper()}")
    print(f"URL: {url}")
    print(f"โฟลเดอร์ปลายทาง: {download_dir}")
    print(f"==================================================")

    # เช็กรายชื่อไฟล์ทั้งหมดที่มีอยู่ในเครื่องก่อน
    existing_files = set(f for f in os.listdir(download_dir) if f.endswith('.pdf'))
    web_filenames = set() # เตรียมตะกร้าไว้เก็บชื่อไฟล์ที่เจอบนเว็บรอบนี้
    
    downloaded_count = 0
    skipped_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print("1. กำลังเปิดหน้าเว็บ BMW Brochure...")
        page.goto(url, timeout=60000)
        page.wait_for_load_state('networkidle')
        time.sleep(3) 

        print("2. กำลังกวาดสายตาหาลิงก์ PDF ทั้งหมด...")
        links = page.locator("a").evaluate_all(
            "elements => elements.map(e => e.href).filter(href => href.toLowerCase().includes('.pdf'))"
        )
        unique_links = list(set(links))
        
        if not unique_links:
            print("!! ไม่พบลิงก์ PDF (อาจจะติด Lazy Loading หรือเว็บมีปัญหา)")
            browser.close()
            return

        print(f"-> เจอลิงก์ PDF ทั้งหมด {len(unique_links)} ลิงก์\n")

        # 3. เริ่มกระบวนการคัดกรองและดาวน์โหลด
        for i, link in enumerate(unique_links, 1):
            # ดึงชื่อไฟล์จาก URL และถอดรหัส (เช่น แปลง %20 เป็นช่องว่าง) ให้เป็นชื่อไฟล์จริงๆ
            raw_filename = link.split('/')[-1].split('?')[0]
            filename = unquote(raw_filename)
            filename_lower = filename.lower()

            # [กฎข้อ 1]: ตัดไฟล์โบรชัวร์การตลาดทิ้ง (เอาเฉพาะ Specsheet)
            # เช็กว่ามีคำว่า brochure, catalog หรือ leaflet อยู่ในชื่อไฟล์หรือไม่
            excluded_keywords = ["brochure", "catalog", "leaflet"]
            if any(keyword in filename_lower for keyword in excluded_keywords):
                continue
            
            # กันเหนียว: ข้ามไฟล์ที่ไม่ได้นามสกุล pdf จริงๆ
            if not filename_lower.endswith('.pdf'):
                continue

            # จดชื่อไฟล์นี้ไว้ในตะกร้า ว่าเว็บยังมีรถรุ่นนี้ขายอยู่
            web_filenames.add(filename)
            all_web_filenames.add(filename)

            # [กฎข้อ 2]: เช็กว่าไฟล์นี้เคยโหลดมาแล้วหรือยัง
            if filename in existing_files:
                print(f"[{i}/{len(unique_links)}] ⏭️ ข้าม (มีในเครื่องแล้ว): {filename}")
                skipped_count += 1
                continue

            # ถ้าผ่านด่านมาถึงตรงนี้ แปลว่าเป็นไฟล์ใหม่ (ต้องดาวน์โหลด)
            print(f"[{i}/{len(unique_links)}] ⬇️ โหลดไฟล์ใหม่: {filename}")
            success = download_pdf(page, link, download_dir, filename)
            
            if success:
                print("   -> สำเร็จ")
                downloaded_count += 1
                # หน่วงเวลา 5 วินาที เฉพาะตอนที่มีการดึงไฟล์ใหม่เท่านั้น (ประหยัดเวลาสุดๆ)
                time.sleep(5)

        browser.close()

    # [กฎข้อ 3]: วิเคราะห์หารถรุ่นที่หายไปจากเว็บ
    print(f"\nรายงานการซิงค์ข้อมูล (Sync Report) สำหรับภาษา {lang.upper()}:")
    print(f"  - โหลดไฟล์ใหม่เพิ่ม: {downloaded_count} ไฟล์")
    print(f"  - ข้ามไฟล์ซ้ำ: {skipped_count} ไฟล์")
    
    # เอาไฟล์ในเครื่อง ตั้งต้น ลบด้วย ไฟล์ที่เว็บบอกว่ามี = ไฟล์ที่ถูกถอดออก
    removed_files = existing_files - web_filenames
    if removed_files:
        print(f"\n[SCRAPER] Found {len(removed_files)} discontinued PDFs. They will be processed and archived by the next step.")
    else:
        print("\n[SCRAPER] No discontinued PDFs detected. Active files match web 100%.")
    print(f"{'='*50}\n")

def run_scraper():
    all_web_filenames.clear()
    for target in TARGETS:
        scrape_target(target)
    
    # Save the consolidated list of live web PDFs
    scratch_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch")
    if not os.path.exists(scratch_dir):
        os.makedirs(scratch_dir)
    list_path = os.path.join(scratch_dir, "live_web_pdfs.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for fname in sorted(all_web_filenames):
            f.write(fname + "\n")
    print(f"\n[SCRAPER] Saved {len(all_web_filenames)} live web PDF filenames to {list_path}")

if __name__ == "__main__":
    run_scraper()