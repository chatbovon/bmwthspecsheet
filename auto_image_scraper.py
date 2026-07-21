import asyncio
import os
import sys
import json
import shutil
from playwright.async_api import async_playwright

# Reconfigure console encoding to UTF-8
sys.stdout.reconfigure(encoding='utf-8')

import difflib

# Configurator specifications for our targeted test models
SCRAPE_CONFIGS = {
    "420i Coupé M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G22/12HBZ0Y",
        "engine_keyword": "420i",
        "image_dir": "images/4series_images",
        "model_key_name": "BMW_420i_Coupe_M_Sport"
    },
    "430i Coupé M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G22/12HBZ0Y",
        "engine_keyword": "430i",
        "image_dir": "images/4series_images",
        "model_key_name": "BMW_430i_Coupe_M_Sport"
    },
    "M440i xDrive": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G22/72HBZ0V",
        "engine_keyword": "M440i",
        "image_dir": "images/4series_images",
        "model_key_name": "BMW_M440i_xDrive"
    },
    "XM 50e": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G09/12CSZ4J",
        "engine_keyword": "XM 50e",
        "image_dir": "images/xm_images",
        "model_key_name": "BMW_XM_50e"
    },
    "XM 50e (Shadow Line)": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G09/12CSZ4J",
        "engine_keyword": "Shadow Line",
        "image_dir": "images/xm_images",
        "model_key_name": "BMW_XM_50e_Shadow_Line"
    },
    "X3 20d xDrive M Sport Pro": {
        "engine_keyword": "20d",
        "model_key_name": "BMW_X3_20d_xDrive_M_Sport_Pro"
    },
    "X3 M50 xDrive": {
        "engine_keyword": "M50",
        "model_key_name": "BMW_X3_M50_xDrive"
    },
    "530e M Sport": {
        "engine_keyword": "530e M Sport",
        "model_key_name": "BMW_530e_M_Sport"
    }
}

async def check_and_dismiss_modals(page):
    # Check and dismiss con-modal-conflict if present
    conflict_modal = page.locator("con-modal-conflict")
    if await conflict_modal.count() > 0:
        confirm_btn = page.locator("con-modal-conflict button:has-text('ตกลง'), con-modal-conflict button:has-text('OK'), con-modal-conflict button:has-text('ดำเนินการต่อ')")
        if await confirm_btn.count() > 0:
            print("  [MODAL] con-modal-conflict detected. Dismissing it...")
            await confirm_btn.first.click()
            await asyncio.sleep(4)
            return True
            
    # Check and dismiss standard con-modal-logic if present
    logic_modal = page.locator("con-modal-logic")
    if await logic_modal.count() > 0:
        confirm_btn = page.locator("con-modal-logic button:has-text('ตกลง'), con-modal-logic button:has-text('OK'), con-modal-logic button:has-text('ดำเนินการต่อ')")
        if await confirm_btn.count() > 0:
            print("  [MODAL] con-modal-logic detected. Dismissing it...")
            await confirm_btn.first.click()
            await asyncio.sleep(4)
            return True
            
    return False

async def hide_viewport_overlays(page):
    await page.evaluate("""() => {
        window._hiddenViewportElements = [];
        const tagsToHide = [
            'con-header', 
            'con-island-navigation', 
            'con-sgt', 
            'con-scroll-next', 
            'con-visualization-button', 
            'con-stage-control-layer',
            'con-stage-save-cta',
            'con-toast-bar-container',
            'con-notification-center',
            'header',
            'section.modular-header-section',
            'con-gcdm-error'
        ];
        function hideRecursive(root) {
            if (!root) return;
            tagsToHide.forEach(tag => {
                const els = root.querySelectorAll ? root.querySelectorAll(tag) : [];
                els.forEach(el => {
                    if (el.style.display !== 'none') {
                        el.style.setProperty('display', 'none', 'important');
                        window._hiddenViewportElements.push(el);
                    }
                });
            });
            const children = root.querySelectorAll ? Array.from(root.querySelectorAll('*')) : [];
            children.forEach(c => {
                if (c.shadowRoot) hideRecursive(c.shadowRoot);
            });
        }
        hideRecursive(document.body);
    }""")
    await asyncio.sleep(1)

async def show_viewport_overlays(page):
    await page.evaluate("""() => {
        if (window._hiddenViewportElements) {
            window._hiddenViewportElements.forEach(el => {
                el.style.display = '';
            });
            window._hiddenViewportElements = [];
        }
    }""")
    await asyncio.sleep(1)

async def capture_360_canvas(page, filename):
    print(f"  [VISUALIZER] Opening 360 view for screenshot...")
    btn_360 = page.locator("con-360-button")
    if await btn_360.count() > 0:
        await btn_360.first.click()
        await asyncio.sleep(6) # Wait for 360 view to render
        
        # Hide overlays using JS inline style
        await page.evaluate("""() => {
            try {
                const modal = document.querySelector('con-app').shadowRoot
                    .querySelector('con-modal-logic').shadowRoot
                    .querySelector('con-modal-360-visualization').shadowRoot;
                
                const closeBtn = modal.querySelector('con-modal-template-a').shadowRoot.querySelector('#closeButton');
                if (closeBtn) closeBtn.style.display = 'none';
                
                const controlLayer = modal.querySelector('con-stage-control-layer');
                if (controlLayer) controlLayer.style.display = 'none';
            } catch (e) {
                console.error("Error hiding overlays:", e);
            }
        }""")
        
        # Take screenshot of con-modal-360-visualization canvas
        canvas_el = page.locator("con-modal-360-visualization canvas").first
        await canvas_el.screenshot(path=filename)
        
        # Compress and resize to 50%
        try:
            from PIL import Image
            with Image.open(filename) as img:
                w, h = img.size
                resized_img = img.resize((w // 2, h // 2), Image.Resampling.LANCZOS)
                resized_img.save(filename, optimize=True, quality=85)
            print(f"    [SUCCESS] Saved screenshot & compressed (50%): {filename}")
        except Exception as e:
            print(f"    [WARNING] Failed to compress screenshot: {e}")
        
        # Show overlays using JS inline style
        await page.evaluate("""() => {
            try {
                const modal = document.querySelector('con-app').shadowRoot
                    .querySelector('con-modal-logic').shadowRoot
                    .querySelector('con-modal-360-visualization').shadowRoot;
                
                const closeBtn = modal.querySelector('con-modal-template-a').shadowRoot.querySelector('#closeButton');
                if (closeBtn) closeBtn.style.display = '';
                
                const controlLayer = modal.querySelector('con-stage-control-layer');
                if (controlLayer) controlLayer.style.display = '';
            } catch (e) {
                console.error("Error showing overlays:", e);
            }
        }""")
        
        # Close 360 view
        close_btn = page.locator("con-modal-360-visualization #closeButton")
        if await close_btn.count() > 0:
            await close_btn.first.click()
            await asyncio.sleep(3)
        return True
    else:
        print("  [WARNING] Could not find 360 button. Taking viewport screenshot instead.")
        
        # Hide overlays recursively before taking viewport screenshot
        await hide_viewport_overlays(page)
        
        await page.screenshot(path=filename)
        
        # Show overlays back immediately
        await show_viewport_overlays(page)
        
        # Compress and resize to 50%
        try:
            from PIL import Image
            with Image.open(filename) as img:
                w, h = img.size
                resized_img = img.resize((w // 2, h // 2), Image.Resampling.LANCZOS)
                resized_img.save(filename, optimize=True, quality=85)
            print(f"    [SUCCESS] Saved viewport screenshot & compressed (50%): {filename}")
        except Exception as e:
            print(f"    [WARNING] Failed to compress viewport screenshot: {e}")
            
        return False

async def discover_series_url(page, series_name):
    url = "https://www.bmw.co.th/th/configurator.html"
    print(f"  [DISCOVERY] Navigating to portal {url} to find series: '{series_name}'...")
    await page.goto(url, timeout=90000)
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(8)
    
    # Dismiss cookie banner
    try:
        accept_btn = page.locator("epaas-consent-drawer-shell button.accept-button")
        if await accept_btn.count() > 0:
            await accept_btn.first.click()
            await asyncio.sleep(2)
    except:
        pass
        
    # Get all configurator links recursively
    links = await page.evaluate("""() => {
        const results = [];
        function search(root) {
            if (!root) return;
            const anchors = root.querySelectorAll ? root.querySelectorAll('a') : [];
            anchors.forEach(a => {
                const href = a.href || '';
                const text = (a.innerText || '').trim();
                if (href.includes('configure.bmw.co.th') || href.includes('/configure/')) {
                    results.push({ text, href });
                }
            });
            const children = root.querySelectorAll ? Array.from(root.querySelectorAll('*')) : [];
            children.forEach(el => {
                if (el.shadowRoot) {
                    search(el.shadowRoot);
                }
            });
        }
        search(document.body);
        return results;
    }""")
    
    # Process links to find the best match for series_name (e.g. "BMW X3")
    clean_series = series_name.replace("BMW ", "").strip().lower()
    target_id = clean_series.replace("series", "").strip()
    
    best_href = None
    best_score = 0
    seen_hrefs = set()
    
    print(f"  [DISCOVERY] Looking for exact token match for target identifier: '{target_id}'")
    
    for link in links:
        href = link["href"]
        text_lower = link["text"].lower()
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        
        # Split text into tokens by spaces/newlines, strip Thai unicode and non-alphanumeric characters
        raw_tokens = text_lower.replace("\n", " ").split()
        tokens = []
        for t in raw_tokens:
            # Strip Thai characters (Unicode range 0x0E00 to 0x0E7F)
            t_no_thai = "".join(c for c in t if not (0x0E00 <= ord(c) <= 0x0E7F))
            clean_tok = "".join(char for char in t_no_thai if char.isalnum())
            if clean_tok:
                tokens.append(clean_tok)
        
        score = 0
        # Check if the target identifier is present as an exact token
        if target_id in tokens:
            score += 100
            
            # Tie breaker: if link text matches clean_series name closely, add points
            if clean_series in text_lower:
                score += 20
                
            ratio = difflib.SequenceMatcher(None, clean_series, text_lower).ratio()
            score += int(ratio * 30)
            
            # Penalize matching '3' with 'i3' or '7' with 'i7'
            if target_id == "3" and "i3" in tokens:
                score -= 40
            if target_id == "7" and "i7" in tokens:
                score -= 40
                
            if score > best_score:
                best_score = score
                best_href = href
            
    if best_href and best_score >= 80:
        print(f"  [DISCOVERY] Best matched configurator URL for '{series_name}' is: {best_href} (Score: {best_score})")
        return best_href
        
    print(f"  [DISCOVERY] [WARNING] Could not find confident dynamic link for series '{series_name}' in portal (Best score: {best_score}).")
    return None

def log_scraper_warning(model_name, best_score, best_candidate):
    warnings_file = "scratch/scraper_warnings.json"
    os.makedirs("scratch", exist_ok=True)
    warnings = []
    if os.path.exists(warnings_file):
        try:
            with open(warnings_file, "r", encoding="utf-8") as f:
                warnings = json.load(f)
        except:
            pass
    # Avoid duplicate warnings for the same model in a single run
    if not any(w["model_name"] == model_name for w in warnings):
        warnings.append({
            "model_name": model_name,
            "best_score": int(best_score),
            "best_candidate": best_candidate
        })
        with open(warnings_file, "w", encoding="utf-8") as f:
            json.dump(warnings, f, ensure_ascii=False, indent=4)

async def select_engine(page, engine_keyword):
    # Try clicking Engine Tab
    engine_tab = page.locator("button:has-text('เครื่องยนต์'), button:has-text('Engine')")
    if await engine_tab.count() > 0:
        print(f"  [NAV] Clicking Engine tab...")
        await engine_tab.first.click()
        await asyncio.sleep(4)
        
        # Extract text of all engine card elements
        card_locators = [
            page.locator("con-sgt-card"),
            page.locator("div.engine-card-labels"),
            page.locator("div.engine-card"),
            page.locator("con-engine-selection-card"),
            page.locator("div.engine-selection-card")
        ]
        
        candidates = []
        for loc in card_locators:
            count = await loc.count()
            for idx in range(count):
                el = loc.nth(idx)
                if await el.is_visible():
                    text = await el.inner_text()
                    if text and text.strip():
                        candidates.append((el, text.strip()))
                    
        if not candidates:
            print("  [NAV] No engine card candidates found. Fallback to direct text selection.")
            card = page.locator("con-sgt-card").filter(has_text=engine_keyword)
            if await card.count() == 0:
                card = page.locator("button").filter(has_text=engine_keyword)
            if await card.count() == 0:
                card = page.get_by_text(engine_keyword)
                
            if await card.count() > 0:
                await card.first.click()
                await asyncio.sleep(3)
                await check_and_dismiss_modals(page)
                return True
            log_scraper_warning(engine_keyword, 0, "No candidates/tabs found")
            return False
            
        # Fuzzy match on the candidate card text
        best_el = None
        best_score = 0
        target = engine_keyword.lower()
        
        for el, text in candidates:
            text_lower = text.lower()
            score = 0
            if target in text_lower:
                score += 100
            for word in target.split():
                if word in text_lower:
                    score += 20
            ratio = difflib.SequenceMatcher(None, target, text_lower).ratio()
            score += int(ratio * 50)
            
            if score > best_score:
                best_score = score
                best_el = el
                
        if best_el:
            card_text = await best_el.inner_text()
            clean_card_text = card_text.replace('\n', ' | ')
            if best_score < 80:
                log_scraper_warning(engine_keyword, best_score, clean_card_text)
                print(f"  [WARNING] Match confidence low (Score: {best_score} < 80) for engine '{engine_keyword}'. Best guess: {clean_card_text}. Logging warning and proceeding.")
            else:
                print(f"  [NAV] Selecting best engine option (Score: {best_score}): {clean_card_text}")
            await best_el.click()
            await asyncio.sleep(4)
            await check_and_dismiss_modals(page)
            await asyncio.sleep(2)
            return True
        else:
            log_scraper_warning(engine_keyword, 0, "No candidates matched")
            print(f"  [WARNING] Could not find any engine card match for '{engine_keyword}'. Skipping.")
            return False
    else:
        print("  [NAV] Engine tab not found, using default pre-selected option.")
        return True

async def scrape_model_paintworks(page, config, model_name):
    base_url = config["base_url"]
    engine_keyword = config["engine_keyword"]
    image_dir = config["image_dir"]
    model_key_name = config["model_key_name"]
    
    os.makedirs(image_dir, exist_ok=True)
    
    print(f"\nNavigating to: {base_url} ...")
    await page.goto(base_url, timeout=90000)
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(8)
    
    # Dismiss cookie consent banner
    try:
        accept_btn = page.locator("epaas-consent-drawer-shell button.accept-button")
        if await accept_btn.count() > 0:
            await accept_btn.first.click()
            await asyncio.sleep(2)
    except Exception as e:
        print("  Cookie banner skipped:", e)
        
    await page.add_style_tag(content="epaas-consent-drawer-shell { display: none !important; }")
    await asyncio.sleep(1)
    
    # Select engine option if necessary
    engine_ok = await select_engine(page, engine_keyword)
    if not engine_ok:
        print(f"  [ERROR] Engine keyword '{engine_keyword}' could not be selected. Skipping.")
        return {}
    
    # Click Paint tab
    print("  [NAV] Clicking 'สี' (Paint) tab...")
    paint_tab = page.locator("button:has-text('สี')")
    if await paint_tab.count() > 0:
        await paint_tab.first.click()
        await asyncio.sleep(4)
    else:
        print("  [ERROR] Paint tab not found! Skipping.")
        return {}
        
    # Get all paint swatches
    paint_swatches = page.locator("con-swatch[data-node-category-alt='Paintwork']")
    count_swatches = await paint_swatches.count()
    print(f"  Found {count_swatches} paint swatches.")
    
    # Find default selected paint swatch first
    initial_code = None
    initial_color_name = None
    for idx in range(count_swatches):
        swatch = paint_swatches.nth(idx)
        is_selected = await swatch.evaluate("""(el) => {
            if (el.classList.contains('is-selected') || el.classList.contains('selected') || el.hasAttribute('selected') || el.getAttribute('aria-checked') === 'true') {
                return true;
            }
            if (el.shadowRoot) {
                const checkedEl = el.shadowRoot.querySelector('[aria-checked="true"], [checked], .is-selected, .selected');
                if (checkedEl) return true;
            }
            return false;
        }""")
        if is_selected:
            initial_code = await swatch.get_attribute("data-node-code")
            initial_color_name = await swatch.get_attribute("data-test-swatch-name")
            break
            
    if not initial_color_name:
        initial_color_name = f"Paint_{initial_code}"
        
    print(f"  [DEFAULT] Default selected paint is: {initial_color_name} (Code: {initial_code})")
    
    # Scraped images dict mapping specsheet color -> filepath
    images_dict = {}
    
    # 1. Capture the default color rendering first
    clean_color_name = initial_color_name.replace(" ", "_").replace("/", "-").replace("\\", "-")
    filename = f"{image_dir}/{(model_key_name + '_' + clean_color_name).lower()}.png"
    
    await check_and_dismiss_modals(page)
    await capture_360_canvas(page, filename)
    
    # Map the default color to its filename
    images_dict[initial_color_name] = filename
    
    # 2. Click and capture remaining swatches
    for i in range(count_swatches):
        swatch = paint_swatches.nth(i)
        color_name = await swatch.get_attribute("data-test-swatch-name")
        paint_code = await swatch.get_attribute("data-node-code")
        if not color_name:
            color_name = f"Paint_{paint_code}"
            
        if paint_code == initial_code:
            continue
            
        print(f"  --- Scraping Paint Swatch #{i+1}: {color_name} (Code: {paint_code}) ---")
        
        await check_and_dismiss_modals(page)
        await swatch.click()
        await asyncio.sleep(2)
        await check_and_dismiss_modals(page)
        await asyncio.sleep(2)
        
        clean_color_name = color_name.replace(" ", "_").replace("/", "-").replace("\\", "-")
        filename = f"{image_dir}/{(model_key_name + '_' + clean_color_name).lower()}.png"
        
        await capture_360_canvas(page, filename)
        images_dict[color_name] = filename
        
    return images_dict

async def main():
    specs_file = "bmw_master_specs.json"
    
    # Load specifications database
    print(f"Loading {specs_file}...")
    with open(specs_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    # Find models lacking the 'images' field
    target_models = []
    db_modified = False
    
    for series in data:
        series_name = series.get("series", "").upper().strip()
        is_m_car = series_name.startswith("BMW M") or series_name.startswith("BMW XM")
        pdf_source = series.get("pdf_source", "unknown")
        clean_pdf = pdf_source.replace(".pdf", "").replace("-", "_").replace(" ", "_")
        for model in series.get("models", []):
            if is_m_car:
                if "images" not in model:
                    model["images"] = {}
                    db_modified = True
                    print(f" - [SKIP] Excluded M Power model from image scraper: {series.get('series')} | {model.get('model_name')}")
                continue
                
            if "images" not in model:
                target_models.append((series, model, clean_pdf))
                
    if db_modified:
        # Write updated mappings back to Thai file
        with open(specs_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        
        # Mirror to English file
        en_file = "bmw_master_specs_en.json"
        if os.path.exists(en_file):
            with open(en_file, "r", encoding="utf-8") as f:
                en_data = json.load(f)
            for s_en in en_data:
                s_name = s_en.get("series", "")
                for m_en in s_en.get("models", []):
                    m_name = m_en.get("model_name", "")
                    for s_up in data:
                        if s_up.get("series") == s_name:
                            for m_up in s_up.get("models", []):
                                if m_up.get("model_name") == m_name and "images" in m_up:
                                    m_en["images"] = m_up["images"]
            with open(en_file, "w", encoding="utf-8") as f:
                json.dump(en_data, f, ensure_ascii=False, indent=4)
        print(f"Saved initialized empty images for M models to databases.")
                    
    if not target_models:
        print("\nNo models found lacking images for the target series. No scraping required!")
        return
        
    print(f"\nFound {len(target_models)} models requiring scraping:")
    for series_obj, model, clean_pdf in target_models:
        print(f" - {series_obj.get('series')} | {model['model_name']} (Folder: images/{clean_pdf})")
        
    async with async_playwright() as p:
        print("\nLaunching browser...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 2560, "height": 1440})
        page = await context.new_page()
        
        for series_obj, model, clean_pdf in target_models:
            model_name = model["model_name"]
            series_name = series_obj.get("series", "")
            
            # Fetch config from SCRAPE_CONFIGS or build on the fly
            if model_name in SCRAPE_CONFIGS:
                config = SCRAPE_CONFIGS[model_name].copy()
            else:
                # Dynamic fallback config
                clean_model_key = model_name.replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_")
                config = {
                    "engine_keyword": model_name,
                    "model_key_name": f"BMW_{clean_model_key}"
                }
                
            config["image_dir"] = f"images/{clean_pdf}"
            
            # Resolve base_url dynamically if not present
            if "base_url" not in config or not config["base_url"]:
                print(f"\n  [DISCOVERY] No base_url for {model_name}. Attempting dynamic discovery...")
                discovered_url = await discover_series_url(page, series_name)
                if discovered_url:
                    config["base_url"] = discovered_url
                else:
                    print(f"  [ERROR] Could not dynamically discover URL for '{series_name}'. Skipping.")
                    continue
            
            print(f"\n==================================================")
            print(f"SCRAPING IMAGES FOR: {model_name}")
            print(f"  [PDF SOURCE]: {series_obj.get('pdf_source')}")
            print(f"  [BASE URL]: {config['base_url']}")
            print(f"  [OUTPUT DIR]: {config['image_dir']}")
            print(f"==================================================")
            
            try:
                images_dict = await scrape_model_paintworks(page, config, model_name)
                
                # Update images key in our model dictionary
                if images_dict:
                    model["images"] = images_dict
                    print(f"Successfully scraped and mapped {len(images_dict)} images for {model_name}.")
            except Exception as e:
                print(f"[ERROR] Failed to scrape {model_name}: {e}")
                
        await browser.close()
        
    # Write updated mappings back to files
    print(f"\nWriting updated specifications back to {specs_file}...")
    with open(specs_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        
    # Mirror changes to the English spec file
    en_file = "bmw_master_specs_en.json"
    if os.path.exists(en_file):
        print(f"Mirroring updates to {en_file}...")
        with open(en_file, "r", encoding="utf-8") as f:
            en_data = json.load(f)
            
        for series in en_data:
            series_name = series.get("series", "")
            for model in series.get("models", []):
                model_name = model.get("model_name", "")
                
                # Find matching model in updated data
                for s_updated in data:
                    if s_updated.get("series") == series_name:
                        for m_updated in s_updated.get("models", []):
                            if m_updated.get("model_name") == model_name and "images" in m_updated:
                                model["images"] = m_updated["images"]
                                
        with open(en_file, "w", encoding="utf-8") as f:
            json.dump(en_data, f, ensure_ascii=False, indent=4)
            
    print("\nAuto-image scraping pipeline finished successfully!")

if __name__ == "__main__":
    asyncio.run(main())
