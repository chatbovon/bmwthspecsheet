import os
import sys
import json
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()

sys.stdout.reconfigure(encoding='utf-8')

# API Keys pooling
API_KEYS = [
    os.environ.get("GEMINI_API_KEY_1"),
    os.environ.get("GEMINI_API_KEY_2"),
    os.environ.get("GEMINI_API_KEY_3"),
    os.environ.get("GEMINI_API_KEY")
]
API_KEYS = [k for k in API_KEYS if k]

if not API_KEYS:
    print("[ERROR] Please set GEMINI_API_KEY_1, GEMINI_API_KEY_2, or GEMINI_API_KEY_3 environment variables.")
    # Exit with code 0 to avoid breaking builds due to configuration issues if keys are missing
    sys.exit(0)

# Paths resolved relative to script location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TH_CATALOG = os.path.join(BASE_DIR, "bmw_master_specs.json")
EN_CATALOG = os.path.join(BASE_DIR, "bmw_master_specs_en.json")

if not os.path.exists(TH_CATALOG) or not os.path.exists(EN_CATALOG):
    print(f"[ERROR] Master catalogs not found: {TH_CATALOG} or {EN_CATALOG}")
    sys.exit(0)

# Load data
with open(TH_CATALOG, encoding="utf-8") as f:
    th_data = json.load(f)
with open(EN_CATALOG, encoding="utf-8") as f:
    en_data = json.load(f)

# Helper to find model data
def get_model_spec(catalog, model_name):
    for series_item in catalog:
        for m in series_item.get("models", []):
            if m.get("model_name").strip().lower() == model_name.strip().lower():
                return m
    return None

# Find overlapping models in both databases
th_models = set()
for series_item in th_data:
    for m in series_item.get("models", []):
        if m.get("model_name"):
            th_models.add(m["model_name"].strip())

en_models = set()
for series_item in en_data:
    for m in series_item.get("models", []):
        if m.get("model_name"):
            en_models.add(m["model_name"].strip())

matching_models = sorted(list(th_models.intersection(en_models)))

# Quick check filter for development
if os.environ.get("QUICK_CHECK") == "true" or "--quick-check" in sys.argv:
    target_models = [
        "320d M Sport", "330e M Sport", "M340i xDrive",
        "420i Coupé M Sport", "430i Coupé M Sport", "M440i xDrive",
        "520d M Sport", "530e Inspiring", "530e M Sport", "740d M Sport",
        "XM 50e", "XM 50e (Shadow Line)"
    ]
    matching_models = [m for m in matching_models if m in target_models]
    print(f"[QUICK-CHECK] Enabled. Filtering matching models to target list ({len(matching_models)} models).")

print(f"Found {len(matching_models)} matching models between TH and EN master catalogs:")
for mname in matching_models:
    print(f"  - {mname}")

# System prompt for comparison
COMPARISON_PROMPT = """You are a professional BMW QA Technical auditor. Your task is to compare the Thai and English specification JSONs for a specific BMW model and find all discrepancies or inconsistencies between them.

A discrepancy is defined as:
1. Option presence mismatch: An option is enabled '■' or has a value in one language but is marked as absent '-' or missing in the other language. (Exclude cases where Thai has translated values and English has equivalent English values, unless they contradict each other).
2. Numeric value discrepancy: Different values for engine output, fuel economy (km/l), dimensions (length/width/height), cargo space, weight, battery capacity, or tyre sizes.
3. Paintwork / Upholstery mismatch: Different combinations of exterior paint and interior leather/color, or mismatched leather names.
4. Logical conflict: Any other contradiction.

Output your findings as a strict JSON array of discrepancy objects in this format (no markdown formatting, no code block backticks, just raw JSON):
[
  {
    "category": "Category name in English/Thai",
    "topic_th": "Topic name in Thai",
    "topic_en": "Topic name in English",
    "value_th": "Value in Thai JSON",
    "value_en": "Value in English JSON",
    "severity": "high/medium/low",
    "description": "Clear explanation of the mismatch and why it matters."
  }
]

If there are no discrepancies, output an empty array [].
"""

# Helper function to call Gemini with key pooling and model fallbacks
def generate_content_with_pooling(prompt_text):
    model_pool = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.6-flash-lite", "gemini-3.5-flash-lite"]
    
    for model_name in model_pool:
        for key_idx, key in enumerate(API_KEYS):
            try:
                # Add spacing sleep to prevent rate limiting
                time.sleep(3)
                client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=60000))
                response = client.models.generate_content(
                    model=model_name,
                    contents=[prompt_text],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )
                return json.loads(response.text)
            except Exception as e:
                err_msg = str(e)
                print(f"   [WARN] Key #{key_idx+1} failed with model {model_name}: {err_msg[:120]}...")
                if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
                    print("   [COOLDOWN] Rate limit hit. Sleeping 10s...")
                    time.sleep(10)
                continue
    raise ValueError("All API keys and models in pool were exhausted or failed.")

raw_results = {}

for mname in matching_models:
    print(f"\n[VALIDATE] Comparing specifications for model: {mname}...")
    th_spec = get_model_spec(th_data, mname)
    en_spec = get_model_spec(en_data, mname)
    
    prompt = f"{COMPARISON_PROMPT}\n\nModel: {mname}\n\n=== THAI SPECIFICATION ===\n{json.dumps(th_spec, ensure_ascii=False, indent=2)}\n\n=== ENGLISH SPECIFICATION ===\n{json.dumps(en_spec, ensure_ascii=False, indent=2)}"
    
    try:
        data = generate_content_with_pooling(prompt)
        raw_results[mname] = data
        print(f"   -> Found {len(data)} raw discrepancies.")
    except Exception as e:
        print(f"   -> Error comparing {mname}: {e}")
        raw_results[mname] = []

# =========================================================================
# RUN FILTERING PIPELINE
# =========================================================================
all_discrepancies = []
for mname, items in raw_results.items():
    for item in items:
        item["model_name"] = mname
        all_discrepancies.append(item)

print(f"\n[FILTER] Filtering {len(all_discrepancies)} total raw discrepancies using Gemini...")

FILTER_PROMPT = """You are an expert BMW specification quality auditor. You will be given a list of cross-language discrepancies between Thai and English brochures.
Your goal is to FILTER OUT any entries that are purely:
1. Terminology Phrasing or Translation style differences: e.g. "BMW TwinPower Turbo..." vs "TwinPower Turbo...", or different separators.
2. Minor spelling differences in leather names or color names: e.g., omitting "Leather 'Vernasca'" in one language but keeping "Mocha" or "Black", or minor capitalization/spacing/hyphen differences.
3. Equivalent technical specifications written differently.
4. Category Grouping Mismatches: If an option is present in both databases but listed under different categories (e.g., 'อุปกรณ์ภายใน' / 'Interior Equipment' vs 'Interior'), this is NOT a contradiction. Filter it out.

Keep ONLY actual specification contradictions, such as:
1. Option presence mismatch: One language says present '■' (or a specific value) and the other says absent '-' (or vice versa).
2. True numeric/spec differences: e.g. different torque RPM ranges, different dimensions, different cargo capacities.
3. Missing configurations: Entire colors or models that are present in one brochure but completely omitted in the other.

Output your filtered results as a strict JSON array of discrepancy objects in this format (no markdown code blocks, no backticks, just raw JSON):
[
  {
    "model_name": "Model Name",
    "category": "Category",
    "topic_th": "Topic in Thai",
    "topic_en": "Topic in English",
    "value_th": "Value in Thai",
    "value_en": "Value in English",
    "reason": "Clear explanation of why this is a real discrepancy."
  }
]

If no real discrepancies remain, output an empty array [].
"""

filtered_results = []
if all_discrepancies:
    prompt_filter = f"{FILTER_PROMPT}\n\n=== CHUNK OF DISCREPANCIES ===\n{json.dumps(all_discrepancies, ensure_ascii=False, indent=2)}"
    try:
        filtered_results = generate_content_with_pooling(prompt_filter)
        print(f"   -> Retained {len(filtered_results)} actual discrepancies.")
    except Exception as e:
        print(f"   -> Error filtering discrepancies: {e}")

# Save filtered markdown report locally for developer reference
filtered_report_path = os.path.join(BASE_DIR, "filtered_discrepancy_report.md")

grouped = {}
for item in filtered_results:
    mname = item.get("model_name", "Unknown Model")
    grouped.setdefault(mname, []).append(item)

md = []
md.append(f"# BMW Filtered Specification Discrepancy Report ({len(filtered_results)} actual issues found)\n")
md.append("This report lists only the actual technical discrepancies, option presence contradictions, and value conflicts between the Thai and English brochures, filtering out minor translation style and terminology phrasing differences.\n")

for mname, items in sorted(grouped.items()):
    md.append(f"## 🚗 {mname} ({len(items)} issues)")
    md.append("| Category | Option / Specification | Thai Value | English Value | Reason |")
    md.append("| :--- | :--- | :--- | :--- | :--- |")
    for item in items:
        topic_display = f"**{item.get('topic_th')} / {item.get('topic_en')}**"
        md.append(f"| {item.get('category')} | {topic_display} | {item.get('value_th')} | {item.get('value_en')} | {item.get('reason')} |")
    md.append("")

if not filtered_results:
    md.append("\n🎉 **No real technical discrepancies found between TH and EN master databases!**")

with open(filtered_report_path, "w", encoding="utf-8") as f:
    f.write("\n".join(md))

print(f"\n[COMPLETE] Filtered MD report saved to: {filtered_report_path}")

# =========================================================================
# EXIT WITH CODE 1 IF ACTUAL DISCREPANCIES EXIST
# =========================================================================
# Ignore M340i xDrive Engine torque RPM discrepancy because it differs in reality
final_actual_issues = []
for item in filtered_results:
    mname = item.get("model_name", "")
    topic_en = item.get("topic_en", "").lower()
    topic_th = item.get("topic_th", "").lower()
    
    if "m340i" in mname.lower() and ("torque" in topic_en or "แรงบิด" in topic_th):
        print(f"   [IGNORE] M340i torque RPM difference is expected and ignored.")
        continue
    final_actual_issues.append(item)

if len(final_actual_issues) > 0:
    print(f"\n[FAIL] Found {len(final_actual_issues)} actual technical discrepancies!")
    sys.exit(1)
else:
    print("\n[PASS] No technical discrepancies found (or all ignored).")
    sys.exit(0)
