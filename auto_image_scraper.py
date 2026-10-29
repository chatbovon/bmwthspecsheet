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
    "220 Gran Coupe M Sport Pro": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/F74/64GGZ9H",
        "engine_keyword": "220",
        "model_key_name": "BMW_220_Gran_Coupe_M_Sport_Pro"
    },
    "320d M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G20/24FWZ7U",
        "engine_keyword": "320d",
        "model_key_name": "BMW_320d_M_Sport"
    },
    "330e M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G20/84BWZ7J",
        "engine_keyword": "330e",
        "model_key_name": "BMW_330e_M_Sport"
    },
    "M340i xDrive": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G20/84FVZ7H",
        "engine_keyword": "M340i",
        "model_key_name": "BMW_M340i_xDrive"
    },
    "320Li M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G28/38FHZ7T",
        "engine_keyword": "320Li",
        "model_key_name": "BMW_320Li_M_Sport"
    },
    "420i Coupé M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G22/12HBZ0Y",
        "engine_keyword": "420i",
        "model_key_name": "BMW_420i_Coupe_M_Sport"
    },
    "430i Coupé M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G22/42HBZ07",
        "engine_keyword": "430i",
        "model_key_name": "BMW_430i_Coupe_M_Sport"
    },
    "M440i xDrive": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G22/72HBZ0V",
        "engine_keyword": "M440i",
        "model_key_name": "BMW_M440i_xDrive"
    },
    "430i Convertible M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G23/32FPZ9A",
        "engine_keyword": "430i",
        "model_key_name": "BMW_430i_Convertible_M_Sport"
    },
    "X1 sDrive20i M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/U11/44EEZ8K",
        "engine_keyword": "20i",
        "model_key_name": "BMW_X1_sDrive20i_M_Sport"
    },
    "iX1 eDrive20L M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/U12/12HNZLD",
        "engine_keyword": "20L",
        "model_key_name": "BMW_iX1_eDrive20L_M_Sport"
    },
    "iX2 xDrive30 M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/U10/72GMZ2O",
        "engine_keyword": "30",
        "model_key_name": "BMW_iX2_xDrive30_M_Sport"
    },
    "X3 20d xDrive M Sport Pro": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G45/44JAZ7V",
        "engine_keyword": "20d",
        "model_key_name": "BMW_X3_20d_xDrive_M_Sport_Pro"
    },
    "X3 M50 xDrive": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G45/34JAZ7X",
        "engine_keyword": "M50",
        "model_key_name": "BMW_X3_M50_xDrive"
    },
    "iX3 50 xDrive M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/NA5/32HRZKS",
        "engine_keyword": "50",
        "model_key_name": "BMW_iX3_50_xDrive_M_Sport"
    },
    "X4 xDrive20d M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G02/28CAZ8T",
        "engine_keyword": "20d",
        "model_key_name": "BMW_X4_xDrive20d_M_Sport"
    },
    "X5 xDrive30d M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G05/14EVZ4Y",
        "engine_keyword": "30d",
        "model_key_name": "BMW_X5_xDrive30d_M_Sport"
    },
    "X5 xDrive50e M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G05/48EUZ5E",
        "engine_keyword": "50e",
        "model_key_name": "BMW_X5_xDrive50e_M_Sport"
    },
    "X6 xDrive40i M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G06/34EXZ4Z",
        "engine_keyword": "40i",
        "model_key_name": "BMW_X6_xDrive40i_M_Sport"
    },
    "X7 xDrive40d M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G07/24ENZ5A",
        "engine_keyword": "40d",
        "model_key_name": "BMW_X7_xDrive40d_M_Sport"
    },
    "530e M Sport": {
        "engine_keyword": "530e M Sport",
        "model_key_name": "BMW_530e_M_Sport"
    },
    "320Li M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G28/38FHZ7T",
        "engine_keyword": "320Li",
        "model_key_name": "BMW_320Li_M_Sport"
    },
    "i7 50 xDrive M Sport": {
        "base_url": "https://configure.bmw.co.th/th_TH/configure/G70/62HYZLL",
        "engine_keyword": "i7 50 xDrive",
        "model_key_name": "BMW_i7_50_xDrive_M_Sport"
    }
}

async def check_and_dismiss_modals(page):
    # Ensure cookie consent overlay does not intercept modal buttons
    try:
        await page.add_style_tag(content="epaas-consent-drawer-shell { display: none !important; pointer-events: none !important; }")
    except Exception:
        pass

    # Check and dismiss con-modal-conflict or con-modal-logic or dialog modals if present
    conflict_modal = page.locator("con-modal-conflict, con-modal-logic, div[role='dialog']")
    if await conflict_modal.count() > 0:
        # Find any confirm button (accept/confirm/ok/proceed)
        confirm_selectors = [
            "button:has-text('ยอมรับ')",
            "con-button:has-text('ยอมรับ')",
            "button:has-text('ยืนยัน')",
            "con-button:has-text('ยืนยัน')",
            "button:has-text('ตกลง')",
            "con-button:has-text('ตกลง')",
            "button:has-text('OK')",
            "con-button:has-text('OK')",
            "button:has-text('ดำเนินการต่อ')",
            "con-button:has-text('ดำเนินการต่อ')"
        ]
        
        for selector in confirm_selectors:
            btn = conflict_modal.locator(selector)
            count = await btn.count()
            if count > 0:
                for idx in range(count):
                    b = btn.nth(idx)
                    try:
                        if await b.is_visible():
                            print(f"  [MODAL] Dismissing modal using selector: {selector} (Button #{idx+1})")
                            try:
                                await b.click(force=True, timeout=4000)
                            except Exception:
                                await b.evaluate("el => el.click()")
                            await asyncio.sleep(5)
                            return True
                    except Exception:
                        pass
                
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
        temp_screen = filename if filename.endswith('.png') else os.path.splitext(filename)[0] + '.png'
        canvas_el = page.locator("con-modal-360-visualization canvas").first
        await canvas_el.screenshot(path=temp_screen)
        
        # Compress and resize to 50%
        try:
            from PIL import Image
            with Image.open(temp_screen) as img:
                w, h = img.size
                resized_img = img.resize((w // 2, h // 2), Image.Resampling.LANCZOS)
                fmt = "WEBP" if filename.endswith('.webp') else "PNG"
                resized_img.save(filename, format=fmt, optimize=True, quality=85)
            if temp_screen != filename and os.path.exists(temp_screen):
                os.remove(temp_screen)
            print(f"    [SUCCESS] Saved 360 screenshot & compressed (50%): {filename}")
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
        
        temp_screen = filename if filename.endswith('.png') else os.path.splitext(filename)[0] + '.png'
        await page.screenshot(path=temp_screen)
        if temp_screen != filename:
            try:
                from PIL import Image
                with Image.open(temp_screen) as img:
                    w, h = img.size
                    resized_img = img.resize((w // 2, h // 2), Image.Resampling.LANCZOS)
                    resized_img.save(filename, format="WEBP", quality=85)
                if os.path.exists(temp_screen):
                    os.remove(temp_screen)
            except Exception as e:
                print(f"    [WARNING] Viewport conversion error: {e}")
        return True


async def capture_stage_or_canvas(page, filename):
    """
    Captures car image.
    Primary: Extracts the direct 3/4 front view image URL from the stage slider,
             downloads the clean native WebP image, and saves it.
    Fallback: Opens 360 mode or captures viewport canvas if stage slider is unavailable.
    """
    print(f"  [VISUALIZER] Attempting direct stage 3/4 front image capture...")
    
    img_url = await page.evaluate("""() => {
        try {
            const app = document.querySelector('con-app');
            if (!app || !app.shadowRoot) return null;
            const configure = app.shadowRoot.querySelector('con-configure');
            if (!configure || !configure.shadowRoot) return null;
            const stage = configure.shadowRoot.querySelector('con-stage-desktop');
            if (!stage || !stage.shadowRoot) return null;
            const slider = stage.shadowRoot.querySelector('con-slider-view');
            if (!slider || !slider.shadowRoot) return null;
            const nativeSlider = slider.shadowRoot.querySelector('con-native-slider');
            if (!nativeSlider || !nativeSlider.shadowRoot) return null;
            
            const imgs = Array.from(nativeSlider.shadowRoot.querySelectorAll('img'));
            const visibleCars = imgs.filter(img => {
                const r = img.getBoundingClientRect();
                return r.width > 500 && r.height > 500 && Math.abs(r.left) < 100;
            });
            return visibleCars.length > 0 ? visibleCars[0].src : null;
        } catch (e) {
            return null;
        }
    }""")
    
    if img_url:
        import urllib.request
        from PIL import Image
        
        webp_filename = filename if filename.endswith('.webp') else os.path.splitext(filename)[0] + '.webp'
        temp_raw = webp_filename + '.tmp'
        try:
            urllib.request.urlretrieve(img_url, temp_raw)
            with Image.open(temp_raw) as img:
                w, h = img.size
                
                # Universal 16:9 Stage Crop Framing
                # Cozy Cloud stage composite positions the vehicle in the lower-left area
                # Target width: 72% of full canvas, Aspect ratio: 16:9, cx: 35.5%, cy: 51.5%
                crop_w = int(w * 0.72)
                crop_h = int(crop_w * 9 / 16)
                cx = int(w * 0.355)
                cy = int(h * 0.515)

                x1 = max(0, cx - crop_w // 2)
                y1 = max(0, cy - crop_h // 2)
                x2 = min(w, x1 + crop_w)
                y2 = min(h, y1 + crop_h)

                if x1 == 0:
                    x2 = min(w, crop_w)
                if y1 == 0:
                    y2 = min(h, crop_h)

                cropped = img.crop((x1, y1, x2, y2))
                cw, ch = cropped.size
                resized = cropped.resize((cw // 2, ch // 2), Image.Resampling.LANCZOS)
                resized.save(webp_filename, format="WEBP", quality=85, method=6)
                
            if os.path.exists(temp_raw):
                os.remove(temp_raw)
                
            print(f"    [SUCCESS] Saved 3/4 front WebP image ({os.path.getsize(webp_filename)} bytes): {webp_filename}")
            return webp_filename
        except Exception as e:
            print(f"    [WARNING] Direct stage download failed ({e}), falling back to 360 canvas.")
            if os.path.exists(temp_raw):
                os.remove(temp_raw)
                
    # Fallback to existing 360 canvas or viewport capture
    await capture_360_canvas(page, filename)
    return filename
        
def detect_body_style(model_name: str, series_name: str = ""):
    """Detect target body style and define required and forbidden tokens."""
    text = f"{series_name} {model_name}".lower()
    if "gran coupe" in text or "gran coupé" in text:
        return {
            "style": "gran_coupe",
            "required": ["gran coupe", "gran coupé", "f74", "g26", "g16"],
            "forbidden": ["convertible", "cabrio", "touring"]
        }
    if "coupe" in text or "coupé" in text:
        return {
            "style": "coupe",
            "required": ["coupe", "coupé", "g22", "g42", "g82", "g87"],
            "forbidden": ["convertible", "cabrio", "g23", "g83", "touring", "gran coupe", "gran coupé"]
        }
    if "convertible" in text or "cabrio" in text:
        return {
            "style": "convertible",
            "required": ["convertible", "cabrio", "g23", "g83", "g29"],
            "forbidden": ["coupe", "coupé", "g22", "touring", "gran coupe", "gran coupé"]
        }
    if "touring" in text:
        return {
            "style": "touring",
            "required": ["touring", "g21", "g61", "g81", "g99"],
            "forbidden": ["sedan", "saloon", "coupe", "convertible"]
        }
    if "gran sedan" in text or "li" in text.split():
        return {
            "style": "gran_sedan",
            "required": ["gran sedan", "li", "g28"],
            "forbidden": ["touring", "convertible", "coupe"]
        }
    return {
        "style": "default",
        "required": [],
        "forbidden": []
    }

def normalize_color_name(name: str) -> str:
    """Extract canonical core color identity by stripping noise prefixes and finish suffixes."""
    import re
    s = name.lower().strip()
    s = re.sub(r'^(bmw\s+individual|individual|m)\s+', '', s)
    s = re.sub(r'\s+(metallic|solid|paintwork|paint)$', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

async def discover_configurator_url(page, series_name, model_name):
    url = "https://configure.bmw.co.th/"
    print(f"  [DISCOVERY] Navigating to portal {url} to find: '{series_name}' | '{model_name}'...")
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
    
    # Process links with Body Style Fingerprinting
    clean_series = series_name.replace("BMW ", "").strip().lower()
    target_id = clean_series.replace("series", "").strip()
    body_info = detect_body_style(model_name, series_name)
    
    best_href = None
    best_score = 0
    seen_hrefs = set()
    
    print(f"  [DISCOVERY] Target Identifier: '{target_id}', Body Style: '{body_info['style']}'")
    
    for link in links:
        href = link["href"]
        text_lower = link["text"].lower()
        full_candidate = f"{text_lower} {href.lower()}"
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        
        # Split text into tokens by spaces/newlines, strip Thai unicode and non-alphanumeric characters
        raw_tokens = text_lower.replace("\n", " ").split()
        tokens = []
        for t in raw_tokens:
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
                
            # Body Style Match Bonus
            if body_info["required"]:
                if any(req in full_candidate for req in body_info["required"]):
                    score += 150
                    
            # Conflict Penalty Guard: strictly eliminate cross-body matches (e.g., Convertible when searching Coupé)
            if body_info["forbidden"]:
                if any(forbid in full_candidate for forbid in body_info["forbidden"]):
                    score -= 500
                
            if score > best_score:
                best_score = score
                best_href = href
            
    if best_href and best_score >= 80:
        print(f"  [DISCOVERY] Best matched configurator URL for '{model_name}' is: {best_href} (Score: {best_score})")
        return best_href
        
    print(f"  [DISCOVERY] [WARNING] Could not find confident dynamic link for '{model_name}' (Best score: {best_score}).")
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

async def scrape_model_paintworks(page, config, model_name, model_obj=None):
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
        
    # Validate model name and Body Style Conflict Guard
    current_url = page.url.lower()
    header_text_clean = ""
    try:
        model_name_locator = page.locator("h4.model-name")
        if await model_name_locator.count() > 0:
            header_text = await model_name_locator.first.inner_text()
            header_text_clean = header_text.strip().lower()
            target_lower = engine_keyword.lower()
            if target_lower not in header_text_clean and header_text_clean not in target_lower:
                print(f"  [ERROR] Model validation failed! Configurator header shows '{header_text}', but expected '{engine_keyword}'. Aborting.")
                return {}
            else:
                print(f"  [VALIDATION] Confirmed model header matches: '{header_text}' (Target: '{engine_keyword}')")
        else:
            print("  [VALIDATION] [WARNING] Could not locate 'h4.model-name' header on screen. Proceeding with caution.")
    except Exception as e:
        print(f"  [VALIDATION] [WARNING] Error checking model header element: {e}. Proceeding.")
        
    # Strict Body Style Conflict Guard
    body_info = detect_body_style(model_name)
    for forbid_kw in body_info["forbidden"]:
        if forbid_kw in current_url or forbid_kw in header_text_clean:
            print(f"  [BODY GUARD REJECTED] Page URL or header matches forbidden term '{forbid_kw}' for target '{model_name}' (Body Style: {body_info['style']})! Aborting.")
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
    
    # Specsheet-Driven Color Verification Guard
    if model_obj:
        expected_colors = []
        for cat in model_obj.get("specifications", []):
            cat_name = cat.get("category", "").lower()
            if "paintwork" in cat_name or "สีตัวถัง" in cat_name:
                expected_colors = [d.get("topic", "") for d in cat.get("details", []) if d.get("value", "").strip() != "-"]
                break
        if expected_colors:
            expected_cores = {normalize_color_name(c) for c in expected_colors if c}
            page_swatch_names = []
            for idx in range(count_swatches):
                swatch = paint_swatches.nth(idx)
                c_name = await swatch.get_attribute("data-test-swatch-name")
                if c_name:
                    page_swatch_names.append(c_name)
            page_cores = {normalize_color_name(c) for c in page_swatch_names if c}
            matched_cores = expected_cores.intersection(page_cores)
            print(f"  [COLOR GUARD] Specsheet core colors ({len(expected_cores)}): {expected_cores}")
            print(f"  [COLOR GUARD] Configurator swatches ({len(page_cores)}): {page_cores}")
            print(f"  [COLOR GUARD] Matched color overlap: {len(matched_cores)}/{len(expected_cores)}")
            if len(expected_cores) > 0 and len(matched_cores) == 0:
                print(f"  [COLOR GUARD REJECTED] Zero overlap with specsheet colors! Possible variant mismatch. Aborting.")
                return {}
    
    # Find default selected paint swatch first
    initial_code = None
    initial_color_name = None
    for idx in range(count_swatches):
        swatch = paint_swatches.nth(idx)
        is_selected = await swatch.evaluate("""(el) => {
            if (el.getAttribute('data-is-selected') === 'true' || el.classList.contains('is-selected') || el.classList.contains('selected') || el.hasAttribute('selected') || el.getAttribute('aria-checked') === 'true') {
                return true;
            }
            if (el.shadowRoot) {
                const checkedEl = el.shadowRoot.querySelector('[data-is-selected="true"], [aria-checked="true"], [checked], .is-selected, .selected');
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
    filename = f"{image_dir}/{(model_key_name + '_' + clean_color_name).lower()}.webp"
    
    await check_and_dismiss_modals(page)
    actual_path = await capture_stage_or_canvas(page, filename)
    
    # Map the default color to its filename
    images_dict[initial_color_name] = actual_path or filename
    
    # 2. Collect all swatch identifiers upfront to protect against dynamic DOM re-ordering
    swatch_items = []
    for idx in range(count_swatches):
        sw = paint_swatches.nth(idx)
        c_code = await sw.get_attribute("data-node-code")
        c_name = await sw.get_attribute("data-test-swatch-name")
        if not c_name:
            c_name = f"Paint_{c_code}"
        if c_code:
            swatch_items.append({"code": c_code, "name": c_name})

    # Click and capture remaining swatches using unique data-node-code locator
    for idx, item in enumerate(swatch_items):
        paint_code = item["code"]
        color_name = item["name"]

        if paint_code == initial_code:
            print(f"  [SKIP INITIAL] Swatch '{color_name}' ({paint_code}) matches initial selected code. Skipping redundant click.")
            continue

        print(f"  --- Scraping Paint Swatch #{idx+1}: {color_name} (Code: {paint_code}) ---")

        # Target swatch by unique code so DOM re-ordering does not cause missed swatches
        swatch = page.locator(f"con-swatch[data-node-code='{paint_code}']")
        if await swatch.count() == 0:
            print(f"  [WARNING] Swatch with code '{paint_code}' not found in current DOM. Retrying...")
            await asyncio.sleep(2)
            swatch = page.locator(f"con-swatch[data-node-code='{paint_code}']")
            if await swatch.count() == 0:
                print(f"  [ERROR] Swatch '{color_name}' ({paint_code}) could not be located. Skipping.")
                continue

        is_now_selected = await swatch.evaluate("""(el) => {
            if (el.getAttribute('data-is-selected') === 'true' || el.classList.contains('is-selected') || el.classList.contains('selected') || el.getAttribute('aria-checked') === 'true') {
                return true;
            }
            if (el.shadowRoot) {
                const checkedEl = el.shadowRoot.querySelector('[data-is-selected="true"], [aria-checked="true"], .is-selected, .selected');
                if (checkedEl) return true;
            }
            return false;
        }""")

        if is_now_selected:
            print(f"  [ALREADY SELECTED] Swatch '{color_name}' ({paint_code}) is already active. Skipping click to prevent deselect.")
        else:
            await check_and_dismiss_modals(page)
            await swatch.first.click()
            await asyncio.sleep(2)
            dismissed = await check_and_dismiss_modals(page)
            if dismissed:
                print(f"  [MODAL DISMISSED] Waiting 5s for stage to re-render '{color_name}'...")
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(2)

        clean_color_name = color_name.replace(" ", "_").replace("/", "-").replace("\\", "-")
        filename = f"{image_dir}/{(model_key_name + '_' + clean_color_name).lower()}.webp"

        actual_path = await capture_stage_or_canvas(page, filename)
        images_dict[color_name] = actual_path or filename
        
    return images_dict

def resolve_unmapped_paints(model, images_dict):
    if not images_dict:
        return images_dict
        
    # Check if there is any Paint_None or Paint_ key in images_dict
    paint_keys = [k for k in images_dict.keys() if k.lower().startswith("paint_")]
    if not paint_keys:
        return images_dict
        
    # Extract expected colors from specifications
    paint_specs = []
    for cat in model.get("specifications", []):
        cat_name = cat.get("category", "")
        if "paintwork" in cat_name.lower() or "สีตัวถัง" in cat_name.lower():
            paint_specs = cat.get("details", [])
            break
            
    expected_colors = []
    for spec in paint_specs:
        color_name = spec.get("topic", "")
        val = spec.get("value", "")
        if color_name and val and val.strip() != "-":
            expected_colors.append(color_name)
            
    if not expected_colors:
        return images_dict
        
    # Check which expected colors are not matched by other non-Paint keys in images_dict
    unmatched_colors = []
    for color in expected_colors:
        norm_spec = color.lower().strip()
        norm_spec_clean = norm_spec.replace("metallic", "").replace("solid", "").strip()
        
        found = False
        for key in images_dict.keys():
            if key.lower().startswith("paint_"):
                continue
            k = key.lower().strip()
            k_clean = k.replace("metallic", "").replace("solid", "").replace("m ", "").replace("individual ", "").strip()
            
            if (norm_spec == k or 
                norm_spec.replace(" ", "") == k.replace(" ", "") or
                norm_spec in k or 
                k in norm_spec or
                norm_spec_clean == k_clean):
                found = True
                break
        if not found:
            unmatched_colors.append(color)
            
    # If there is exactly one Paint_ key and exactly one unmatched expected color:
    if len(paint_keys) == 1 and len(unmatched_colors) == 1:
        old_key = paint_keys[0]
        new_key = unmatched_colors[0]
        old_path = images_dict[old_key]
        
        # Rename file on disk to match new key
        model_key_name = model.get("model_name", "").replace(" ", "_")
        clean_color_name = new_key.replace(" ", "_").replace("/", "-").replace("\\", "-")
        ext = os.path.splitext(old_path)[1] or ".webp"
        new_filename = f"{os.path.dirname(old_path)}/{(model_key_name + '_' + clean_color_name).lower()}{ext}"
        
        try:
            if os.path.exists(old_path):
                if os.path.exists(new_filename):
                    os.remove(new_filename)
                os.rename(old_path, new_filename)
                print(f"  [REMAP] Renamed default paint file: {old_path} -> {new_filename}")
            images_dict[new_key] = new_filename
            del images_dict[old_key]
            print(f"  [REMAP] Successfully remapped '{old_key}' to expected paint '{new_key}'")
        except Exception as e:
            print(f"  [REMAP] [ERROR] Failed to rename/remap default paint: {e}")
            
    return images_dict

async def main():
    import sys
    model_filter = None
    force_scrape = False
    for i, arg in enumerate(sys.argv):
        if arg == "--model" and i + 1 < len(sys.argv):
            model_filter = sys.argv[i + 1].lower()
        if arg == "--force":
            force_scrape = True

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
            model_name = model.get("model_name", "")
            if model_filter == "x1-x7":
                s_low = series_name.lower()
                m_low = model_name.lower()
                if not any(f"x{n}" in s_low or f"ix{n}" in s_low or f"x{n}" in m_low or f"ix{n}" in m_low for n in range(1, 8)):
                    continue
            elif model_filter in ["2-4", "234", "2-3-4"]:
                s_low = series_name.lower()
                if not any(f"{n} series" in s_low for n in [2, 3, 4]):
                    continue
            elif model_filter and model_filter not in model_name.lower() and model_filter not in series_name.lower():
                continue
            if is_m_car:
                if "images" not in model:
                    model["images"] = {}
                    db_modified = True
                    print(f" - [SKIP] Excluded M Power model from image scraper: {series.get('series')} | {model.get('model_name')}")
                continue
                
            # Check if model has no images or has missing images compared to expected specsheet colors
            needs_scraping = False
            if "images" not in model or not model["images"]:
                needs_scraping = True
            else:
                expected_colors = []
                for cat in model.get("specifications", []):
                    cat_name = cat.get("category", "").lower()
                    if "paintwork" in cat_name or "สีตัวถัง" in cat_name:
                        expected_colors = [d.get("topic", "") for d in cat.get("details", []) if d.get("value", "").strip() != "-"]
                        break
                if expected_colors:
                    existing_keys = [k.lower().replace(" ", "").replace("metallic", "").replace("solid", "") for k in model.get("images", {}).keys()]
                    for exp_c in expected_colors:
                        norm_exp = exp_c.lower().replace(" ", "").replace("metallic", "").replace("solid", "")
                        if not any(norm_exp in k or k in norm_exp for k in existing_keys):
                            needs_scraping = True
                            print(f" - [INCOMPLETE IMAGES] Model {model.get('model_name')} is missing image for expected color '{exp_c}'. Scheduling scrape.")
                            break

            if force_scrape or needs_scraping:
                # Perform case-insensitive directory resolution to match physical folders on disk
                disk_pdf_dir = clean_pdf
                if os.path.exists("images"):
                    for d in os.listdir("images"):
                        if d.lower() == clean_pdf.lower():
                            disk_pdf_dir = d
                            break
                target_models.append((series, model, disk_pdf_dir))
                
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
                discovered_url = await discover_configurator_url(page, series_name, model_name)
                if discovered_url:
                    config["base_url"] = discovered_url
                else:
                    print(f"  [ERROR] Could not dynamically discover URL for '{model_name}'. Skipping.")
                    continue
            
            print(f"\n==================================================")
            print(f"SCRAPING IMAGES FOR: {model_name}")
            print(f"  [PDF SOURCE]: {series_obj.get('pdf_source')}")
            print(f"  [BASE URL]: {config['base_url']}")
            print(f"  [OUTPUT DIR]: {config['image_dir']}")
            print(f"==================================================")
            
            try:
                images_dict = await scrape_model_paintworks(page, config, model_name, model)
                
                # Automatically resolve unmapped default paints to the single missing expected color
                images_dict = resolve_unmapped_paints(model, images_dict)
                
                # Update images key in our model dictionary
                if images_dict:
                    if "images" in model and isinstance(model["images"], dict):
                        model["images"].update(images_dict)
                    else:
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
