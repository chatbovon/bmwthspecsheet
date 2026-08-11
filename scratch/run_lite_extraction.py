import os
import sys
import json
import time

sys.stdout.reconfigure(encoding='utf-8')

# Ensure scratch directory exists
os.makedirs('scratch', exist_ok=True)

# 1. Create a custom version of mineru_extractor for gemini-3.5-flash-lite
with open('mineru_extractor.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Replace MODEL_NAME and model pool arrays to force gemini-3.5-flash-lite
code = code.replace(
    'MODEL_NAME = "gemini-3.6-flash"',
    'MODEL_NAME = "gemini-3.5-flash-lite"'
)
code = code.replace(
    'model_pool = [MODEL_NAME, "gemini-3.5-flash", "gemini-3.6-flash-lite", "gemini-3.5-flash-lite"]',
    'model_pool = ["gemini-3.5-flash-lite"]'
)

# Write out the temporary extractor module
lite_extractor_path = os.path.join('scratch', 'mineru_extractor_lite.py')
with open(lite_extractor_path, 'w', encoding='utf-8') as f:
    f.write(code)

print("[LITE-RUNNER] Created scratch/mineru_extractor_lite.py targeting only 'gemini-3.5-flash-lite'.")

# Now import the customized runner function
sys.path.append(os.path.abspath('scratch'))
from mineru_extractor_lite import run_extraction_pipeline

# 2. Define target brochures mapping
targets_th = [
    ("2-20260622-01_TH.pdf.asset.1782450623206.pdf", "bmw_brochures_auto"),
    ("4-20260714-01_TH_.pdf.asset.1784613825348.pdf", "bmw_brochures_auto"),
    ("7-20250130-02_TH.pdf.asset.1745407582934.pdf", "bmw_brochures_auto"),
    ("i7-20240710-01_TH.pdf.asset.1758628809179.pdf", "bmw_brochures_auto"),
    ("i5-20260714-01_TH.pdf.asset.1784613825396.pdf", "bmw_brochures_auto"),
]

targets_en = [
    ("2-20260622-01_EN.pdf.asset.1782449002094.pdf", "bmw_brochures_auto_en"),
    ("4-20260714-01_EN_.pdf.asset.1784613825320.pdf", "bmw_brochures_auto_en"),
    ("7-20250130-02_EN.pdf.asset.1745391122471.pdf", "bmw_brochures_auto_en"),
    ("i7-20240710-01_EN-(1).pdf.asset.1738060141181.pdf", "bmw_brochures_auto_en"),
    ("i5-20260714-01_EN.pdf.asset.1784613855387.pdf", "bmw_brochures_auto_en"),
]

def run_extraction_for_list(targets, lang, output_db_path):
    print(f"\n[LITE-RUNNER] Starting {lang.upper()} extractions...")
    results = []
    
    for filename, folder in targets:
        pdf_path = os.path.join(folder, filename)
        # Construct temp_json path exactly as batch_extractor does so that it resolves existing md_debug_path correctly!
        temp_json = f"temp_{filename.rsplit('.', 1)[0]}.json"
        
        if os.path.exists(temp_json):
            os.remove(temp_json)
            
        print(f"\n--- Extracting target: {filename} ({lang.upper()}) ---")
        try:
            run_extraction_pipeline(pdf_path, temp_json, lang)
            
            if os.path.exists(temp_json):
                with open(temp_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                data["pdf_source"] = filename
                data["source_file"] = filename
                results.append(data)
                os.remove(temp_json)
                print(f"-> Successfully extracted: {filename}")
            else:
                print(f"[ERROR] Temp output JSON not found for {filename}")
        except Exception as e:
            print(f"[ERROR] Extraction failed for {filename}: {e}")
            
    with open(output_db_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=4)
    print(f"[LITE-RUNNER] Saved consolidated database to: {output_db_path}")

# Run Thai and English
run_extraction_for_list(targets_th, "th", "scratch/lite_master_specs.json")
run_extraction_for_list(targets_en, "en", "scratch/lite_master_specs_en.json")
print("\n[LITE-RUNNER] All extractions complete.")
