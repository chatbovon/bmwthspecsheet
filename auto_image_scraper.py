import asyncio
import os
import sys
import json
import shutil
from playwright.async_api import async_playwright

# Reconfigure console encoding to UTF-8
sys.stdout.reconfigure(encoding='utf-8')

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
        await page.screenshot(path=filename)
        
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

async def select_engine(page, engine_keyword):
    # Try clicking Engine Tab
    engine_tab = page.locator("button:has-text('เครื่องยนต์'), button:has-text('Engine')")
    if await engine_tab.count() > 0:
        print(f"  [NAV] Clicking Engine tab...")
        await engine_tab.first.click()
        await asyncio.sleep(4)
        
        # Target the specific engine card using filters or text search safely
        card = page.locator("div.engine-card-labels").filter(has_text=engine_keyword)
        if await card.count() == 0:
            card = page.locator("button").filter(has_text=engine_keyword)
        if await card.count() == 0:
            card = page.get_by_text(engine_keyword)
            
        if await card.count() > 0:
            print(f"  [NAV] Selecting engine option matching: '{engine_keyword}'...")
            await card.first.click()
            await asyncio.sleep(3)
            await check_and_dismiss_modals(page)
            await asyncio.sleep(2)
            return True
        else:
            print(f"  [WARNING] Could not find engine card with keyword '{engine_keyword}'")
    else:
        print("  [NAV] Engine tab not found, using default pre-selected option.")
    return False

async def scrape_model_paintworks(page, config, model_name):
    base_url = config["base_url"]
    engine_keyword = config["engine_keyword"]
    image_dir = config["image_dir"]
    model_key_name = config["model_key_name"]
    
    os.makedirs(image_dir, exist_ok=True)
    
    print(f"\nNavigating to: {base_url} ...")
    await page.goto(base_url, timeout=90000)
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(6)
    
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
    await select_engine(page, engine_keyword)
    
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
    filename = f"{image_dir}/{model_key_name}_{clean_color_name}.png"
    
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
        filename = f"{image_dir}/{model_key_name}_{clean_color_name}.png"
        
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
    for series in data:
        pdf_source = series.get("pdf_source", "unknown")
        clean_pdf = pdf_source.replace(".pdf", "").replace("-", "_").replace(" ", "_")
        for model in series.get("models", []):
            model_name = model.get("model_name", "")
            if "images" not in model:
                # This model needs scraping!
                if model_name in SCRAPE_CONFIGS:
                    target_models.append((series, model, clean_pdf))
                    
    if not target_models:
        print("\nAll models already have images. No scraping required!")
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
            
            # Dynamically override image_dir based on the source PDF name
            config = SCRAPE_CONFIGS[model_name].copy()
            config["image_dir"] = f"images/{clean_pdf}"
            
            print(f"\n==================================================")
            print(f"SCRAPING IMAGES FOR: {model_name}")
            print(f"  [PDF SOURCE]: {series_obj.get('pdf_source')}")
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
