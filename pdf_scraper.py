import os
import sys
import time
import json
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
        response = page.request.get(pdf_url, timeout=45000)
        if response.ok:
            with open(os.path.join(download_dir, filename), 'wb') as f:
                f.write(response.body())
            return True
        else:
            print(f"   -> [Error] Server return HTTP {response.status}")
    except Exception as e:
        print(f"   -> [Error] {e}")
    return False

EXCLUDED_FILENAME_KEYWORDS = ("brochure", "catalog", "leaflet")
EXCLUDED_LINK_KEYWORDS = ("โบรชัวร์", "brochure", "catalog", "leaflet")


def collect_unique_pdf_links(link_records):
    """Group PDF anchor records by href while keeping all observed link labels."""
    grouped = {}
    for record in link_records:
        if isinstance(record, str):
            href, label = record, ""
        else:
            href = (record.get("href") or "").strip()
            label = " ".join(
                part.strip()
                for part in (
                    record.get("text") or "",
                    record.get("aria") or "",
                    record.get("title") or "",
                )
                if part and part.strip()
            )
        if not href or ".pdf" not in href.lower():
            continue
        grouped.setdefault(href, []).append(label)
    return list(grouped.items())


def is_marketing_brochure(filename, labels=()):
    """Return (True, reason) if PDF filename or all anchor labels indicate a marketing brochure."""
    filename_lower = (filename or "").lower()
    if any(keyword in filename_lower for keyword in EXCLUDED_FILENAME_KEYWORDS):
        return True, "filename"

    non_empty_labels = [" ".join(lbl.lower().split()) for lbl in (labels or ()) if lbl and lbl.strip()]
    if non_empty_labels and all(
        any(keyword in lbl for keyword in EXCLUDED_LINK_KEYWORDS)
        for lbl in non_empty_labels
    ):
        return True, "link_label"

    return False, ""


all_web_filenames = set()
all_web_pdf_urls = {}

def scrape_target(target):
    global all_web_filenames, all_web_pdf_urls
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
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ]
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        max_nav_retries = 2
        nav_success = False
        for attempt in range(1, max_nav_retries + 1):
            try:
                print(f"1. กำลังเปิดหน้าเว็บ BMW Brochure (ครั้งที่ {attempt}/{max_nav_retries})...")
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # Graceful wait for networkidle without throwing fatal error
                try:
                    page.wait_for_load_state('networkidle', timeout=12000)
                except Exception:
                    print("   -> [Notice] Network idle timed out or background telemetry active; continuing with DOM.")
                
                # Give dynamic PDF links time to mount
                try:
                    page.wait_for_selector("a[href*='.pdf']", timeout=15000)
                except Exception:
                    pass

                time.sleep(3)
                nav_success = True
                break
            except Exception as e:
                print(f"   -> [Warning] โหลดหน้าเว็บไม่สำเร็จ (attempt {attempt}): {e}")
                if attempt < max_nav_retries:
                    time.sleep(5)

        if not nav_success:
            print(f"!! [ERROR] ไม่สามารถโหลดหน้าเว็บ BMW Brochure ({lang.upper()}) ได้หลังจากพยายาม {max_nav_retries} ครั้ง")
            try:
                context.close()
            except Exception:
                pass
            browser.close()
            return False

        print("2. กำลังกวาดสายตาหาลิงก์ PDF ทั้งหมด...")
        raw_link_records = page.locator("a").evaluate_all(
            r"""elements => elements
                .filter(e => (e.href || '').toLowerCase().includes('.pdf'))
                .map(e => ({
                    href: e.href,
                    text: (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim(),
                    aria: e.getAttribute('aria-label') || '',
                    title: e.getAttribute('title') || ''
                }))"""
        )
        unique_links = collect_unique_pdf_links(raw_link_records)

        if not unique_links:
            print("!! ไม่พบลิงก์ PDF (อาจจะติด Lazy Loading หรือเว็บมีปัญหา)")
            try:
                context.close()
            except Exception:
                pass
            browser.close()
            return False

        print(f"-> เจอลิงก์ PDF ทั้งหมด {len(unique_links)} ลิงก์\n")

        # 3. เริ่มกระบวนการคัดกรองและดาวน์โหลด
        for i, (link, labels) in enumerate(unique_links, 1):
            # ดึงชื่อไฟล์จาก URL และถอดรหัส (เช่น แปลง %20 เป็นช่องว่าง) ให้เป็นชื่อไฟล์จริงๆ
            raw_filename = link.split('/')[-1].split('?')[0]
            filename = unquote(raw_filename)
            filename_lower = filename.lower()

            # กันเหนียว: ข้ามไฟล์ที่ไม่ได้นามสกุล pdf จริงๆ
            if not filename_lower.endswith('.pdf'):
                continue

            # [กฎข้อ 1]: ตัดไฟล์โบรชัวร์การตลาดทิ้ง (เอาเฉพาะ Specsheet)
            # เช็กทั้งชื่อไฟล์ (brochure, catalog, leaflet) และข้อความบนลิงก์ (เช่น โบรชัวร์ / Brochure)
            excluded, exclude_reason = is_marketing_brochure(filename, labels)
            if excluded:
                if exclude_reason == "link_label":
                    display_label = next((lbl for lbl in labels if lbl), "")
                    print(f"[{i}/{len(unique_links)}] ⏭️ ข้ามโบรชัวร์การตลาด (จากข้อความลิงก์ '{display_label}'): {filename}")
                continue

            # จดชื่อไฟล์นี้ไว้ในตะกร้า ว่าเว็บยังมีรถรุ่นนี้ขายอยู่
            web_filenames.add(filename)
            all_web_filenames.add(filename)
            all_web_pdf_urls[filename] = link

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

        try:
            context.close()
        except Exception:
            pass
        browser.close()

    # [กฎข้อ 3]: วิเคราะห์หารถรุ่นที่หายไปจากเว็บ
    print(f"\nรายงานการซิงค์ข้อมูล (Sync Report) สำหรับภาษา {lang.upper()}:")
    print(f"  - โหลดไฟล์ใหม่เพิ่ม: {downloaded_count} ไฟล์")
    print(f"  - ข้ามไฟล์ซ้ำ: {skipped_count} ไฟล์")
    
    if len(web_filenames) < 5:
        print(f"!! [CIRCUIT BREAKER] Found only {len(web_filenames)} specsheet PDFs for {lang.upper()} (< 5). Marking target scrape incomplete.")
        return False

    # เอาไฟล์ในเครื่อง ตั้งต้น ลบด้วย ไฟล์ที่เว็บบอกว่ามี = ไฟล์ที่ถูกถอดออก
    removed_files = existing_files - web_filenames
    if removed_files:
        print(f"\n[SCRAPER] Found {len(removed_files)} discontinued PDFs. They will be processed and archived by the next step.")
    else:
        print("\n[SCRAPER] No discontinued PDFs detected. Active files match web 100%.")
    print(f"{'='*50}\n")
    return True

def run_scraper():
    all_web_filenames.clear()
    all_web_pdf_urls.clear()
    target_results = {}
    for target in TARGETS:
        lang = target.get("lang", "unknown")
        try:
            target_results[lang] = bool(scrape_target(target))
        except Exception as e:
            print(f"[SCRAPER] [ERROR] Unhandled error scraping target {lang}: {e}")
            target_results[lang] = False

    scratch_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch")
    if not os.path.exists(scratch_dir):
        os.makedirs(scratch_dir)
    list_path = os.path.join(scratch_dir, "live_web_pdfs.txt")
    mapping_path = os.path.join(scratch_dir, "live_web_pdf_urls.json")

    all_targets_ok = (len(target_results) == len(TARGETS)) and all(target_results.values())
    if not all_targets_ok:
        print(f"\n[SCRAPER] [CIRCUIT BREAKER] Scrape incomplete ({target_results}). Refusing to write partial live_web_pdfs.txt or archive databases.")
        for stale_path in (list_path, mapping_path):
            if os.path.exists(stale_path):
                try:
                    os.remove(stale_path)
                    print(f"[SCRAPER] Removed stale file: {stale_path}")
                except Exception as rm_err:
                    print(f"[SCRAPER] [WARNING] Could not remove stale file {stale_path}: {rm_err}")
        return False

    # Save the consolidated list of live web PDFs and URL mapping
    with open(list_path, "w", encoding="utf-8") as f:
        for fname in sorted(all_web_filenames):
            f.write(fname + "\n")
    print(f"\n[SCRAPER] Saved {len(all_web_filenames)} live web PDF filenames to {list_path}")

    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump(all_web_pdf_urls, f, indent=2, ensure_ascii=False)
    print(f"[SCRAPER] Saved {len(all_web_pdf_urls)} live web PDF URLs to {mapping_path}")

    # Synchronize pdf_url into master catalog JSONs
    for db_file in ["bmw_master_specs.json", "bmw_master_specs_en.json"]:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), db_file)
        if os.path.exists(db_path):
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                updated = False
                for item in data:
                    pdf_name = item.get("pdf_source") or item.get("source_file")
                    if pdf_name and pdf_name in all_web_pdf_urls:
                        if item.get("pdf_url") != all_web_pdf_urls[pdf_name]:
                            item["pdf_url"] = all_web_pdf_urls[pdf_name]
                            updated = True
                if updated:
                    with open(db_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                    print(f"[SCRAPER] Updated live pdf_url in {db_file}")
            except Exception as e:
                print(f"[SCRAPER] [WARNING] Failed to update pdf_url in {db_file}: {e}")
    return True

if __name__ == "__main__":
    scrape_ok = run_scraper()

    # Automatically run database synchronization and pruning only when all targets scraped cleanly
    if scrape_ok:
        try:
            print("\n[SCRAPER] Triggering database sync and pruning...")
            import sync_database
            sync_database.main()
        except Exception as e:
            print(f"[WARNING] Automatic database sync failed: {e}")
    else:
        print("[SCRAPER] [CIRCUIT BREAKER] Skipping sync_database due to incomplete scrape.")