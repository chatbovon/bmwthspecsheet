import asyncio, os, sys
from playwright.async_api import async_playwright
from PIL import Image

sys.stdout.reconfigure(encoding='utf-8')

PROOFS_DIR = "images/proofs"
os.makedirs(PROOFS_DIR, exist_ok=True)

TARGETS = [
    {
        "id": "m760e_xdrive",
        "name": "BMW M760e xDrive (New)",
        "url": "https://www.bmw.co.th/th/all-models/m-series/sedan/bmw-7-series-sedan-m-models-technical-data.html/bmw-m760e-xdrive-sedan.bmw",
        "search_text": "กำลังการชาร์จ"
    },
    {
        "id": "750e_xdrive",
        "name": "BMW 750e xDrive M Sport",
        "url": "https://www.bmw.co.th/th/all-models/7-series/7-series-sedan/bmw-7-series-sedan.html/bmw-740d-m-sport.bmw",
        "search_text": "กำลังการชาร์จ"
    },
    {
        "id": "530e_phev",
        "name": "BMW 530e Inspiring / M Sport",
        "url": "https://www.bmw.co.th/th/all-models/5-series/sedan/bmw-5-series-sedan-phev-overview.html",
        "search_text": "กำลังการชาร์จ"
    },
    {
        "id": "330e_m_sport",
        "name": "BMW 330e M Sport",
        "url": "https://www.bmw.co.th/th/all-models/3-series/bmw-3-series-sedan/bmw-3-series-sedan-plug-in-hybrid.html/the-new-330e-m-sport.bmw",
        "search_text": "การชาร์จ"
    },
    {
        "id": "x5_50e",
        "name": "BMW X5 xDrive50e M Sport",
        "url": "https://www.bmw.co.th/th/all-models/x-series/x5/bmw-x5-technical-data.html",
        "search_text": "กำลังการชาร์จ"
    },
    {
        "id": "xm",
        "name": "BMW XM / Label Red / 50e",
        "url": "https://www.bmw.co.th/th/all-models/m-series/xm/bmw-xm-technical-data.html",
        "search_text": "กำลังการชาร์จ"
    },
    {
        "id": "m5_sedan",
        "name": "BMW M5 Sedan",
        "url": "https://www.bmw.co.th/th/all-models/m-series/m5-series/bmw-m5-sedan-technical-data.html",
        "search_text": "กำลังการชาร์จ"
    },
    {
        "id": "m5_touring",
        "name": "BMW M5 Touring",
        "url": "https://www.bmw.co.th/th/all-models/m-series/m5-series/bmw-m5-touring-technical-data.html",
        "search_text": "กำลังการชาร์จ"
    },
    {
        "id": "m760e_older_archived",
        "name": "BMW M760e xDrive (Older Archived)",
        "url": "https://web.archive.org/web/20231128145210/https://www.bmw.co.th/th/all-models/7-series/7-series-sedan/bmw-7-series-sedan.html",
        "search_text": "M760e"
    }
]

async def capture_all():
    print(f"Starting capture for {len(TARGETS)} targets into {PROOFS_DIR}...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1600, "height": 1200},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        for idx, t in enumerate(TARGETS, start=1):
            target_id = t["id"]
            name = t["name"]
            url = t["url"]
            search_text = t.get("search_text", "")
            raw_png = os.path.join(PROOFS_DIR, f"{target_id}_proof.png")
            final_webp = os.path.join(PROOFS_DIR, f"{target_id}_proof.webp")

            print(f"[{idx}/{len(TARGETS)}] Loading {name} ...")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=35000)
                await asyncio.sleep(2.5)

                # Dismiss cookie consent dialog if present
                try:
                    accept_btn = page.locator('button:has-text("ยอมรับทั้งหมด"), button:has-text("Accept all"), button:has-text("ยอมรับ"), button:has-text("Accept")')
                    if await accept_btn.count() > 0:
                        await accept_btn.first.click()
                        await asyncio.sleep(1)
                except Exception:
                    pass

                # Scroll to find charging section or relevant text
                if search_text:
                    await page.evaluate(f"""() => {{
                        const elements = Array.from(document.querySelectorAll('*'));
                        const el = elements.find(e => e.innerText && e.innerText.includes('{search_text}'));
                        if (el) el.scrollIntoView({{ behavior: 'instant', block: 'center' }});
                    }}""")
                    await asyncio.sleep(1.5)

                # Capture full viewport screenshot
                await page.screenshot(path=raw_png, full_page=False)

                # Convert to optimized WebP
                im = Image.open(raw_png)
                im.save(final_webp, "WEBP", quality=85)
                # Keep PNG or clean up
                os.remove(raw_png)

                size_kb = os.path.getsize(final_webp) / 1024
                print(f"   Saved {final_webp} ({size_kb:.1f} KB)")
            except Exception as e:
                print(f"   [ERROR] Failed to capture {name}: {e}")

        await browser.close()
        print("Capture completed.")

if __name__ == "__main__":
    asyncio.run(capture_all())
