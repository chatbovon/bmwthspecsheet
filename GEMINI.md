# Project Context & Workspace Rules: BMW Dynamic Specsheet
BMW Dynamic Specsheet: Extracting tech specs from PDFs into JSON, and displaying them on an HTML frontend.

## 1. API Keys & Environments
- **3 API Keys Configured:** The project utilizes 3 Gemini API keys for pooling and rate limit rotation: `GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`, and `GEMINI_API_KEY_3`.
- **Dynamic Loading Required:** Always load API keys dynamically from the `.env` file in the workspace root. **NEVER hardcode API keys** in Python scripts or environment variables during testing.
- **MinerU API Token:** Always load `MINERU_API_TOKEN` dynamically from the `.env` file.

## 2. Models Setup
- **Primary Model:** Use `gemini-3.5-flash-lite` as primary for all extraction and validation tasks due to its superior speed, light resource footprint, and quota efficiency.
- **Fallback Chain:** Fallback to `gemini-3.6-flash`, `gemini-3.7-flash`, and `gemini-3.8-flash` only when needed.

## 3. PDF Extraction & Table Grouping Constraints
- **At Most 5 Pages:** BMW PDF brochures are at most 5 pages.
- **Segment Limit:** The table splitting logic must group tables to output at most 2 or 3 segments per PDF.
- **Size Threshold:** Combine small adjacent tables together up to ~7,000 characters per segment. This drastically reduces API calls, prevents rate limit exhaustion, and keeps the output well within Gemini's token limits.
- **JSON Structure:** Keys MUST be in `snake_case` English. Values will be mixed Thai/English. DO NOT translate or hallucinate any data.
- **Matrix Data (■):** The "■" symbol indicates an option match. Map it correctly to the column header.

## 4. Frontend & Search Guidelines
- **Frontend Search:** The JS search logic must be case-insensitive and support fuzzy matching for mixed Thai-English keywords.
- **No Code Breakage:** Ensure existing column toggle functions in `index.html` remain intact when adding new features.

## 5. Planning, Scope & Execution Limits
- **Always Plan First:** Before making any modifications to the codebase (no matter how minor or simple they are), you must present a detailed implementation plan and obtain the user's explicit approval first. Do not make changes without permission.
- **Scope and Authorization:** If any proposed work is not explicitly within the scope of the user's instructions, you MUST report the situation and obtain explicit user permission first. Unauthorized modifications or background tasks are strictly prohibited to prevent wasting resources (API quota, CPU/GPU processing, time) and to maintain system reliability.
- **Targeted Execution Scope:** NEVER run full-database or global scripts (such as auditing all models using `run_production_validation.py`) when testing or verifying a specific model change. Always write targeted, small-scope check scripts or directly query the database to verify changes within 2 minutes.
- **Time and Resource Estimations:** Before running any command or proposal that is expected to take over 2 minutes or consume significant API quota, the agent must estimate the run time, explain API usage, and seek explicit user confirmation.

## 6. Strict Plan-to-Code Fidelity & No Premature Shortcut
- **1:1 Architecture Mapping:** Whenever an architectural plan or workflow is agreed upon with the user (e.g., a multi-stage pipeline like Section 1 -> 2 -> 3 -> 4), the implementation must strictly map each stage 1:1 in the code.
- **No Unauthorized Stage Merging:** The agent is strictly prohibited from merging stages, skipping intermediate steps, or taking shortcuts in the code (e.g., combining text cleansing and spec extraction into a single prompt/call) under the pretext of optimization or quota preservation, unless explicitly authorized by the user.
- **Intermediate Artifacts Required:** In any multi-stage pipeline, the agent must save or log intermediate outputs (e.g., cleaned markdown from Stage 1) to verify that each stage actually executed as designed before feeding data to the next stage.

## 7. Manual Overrides Design Philosophy
- **PDF-Level Correction:** The manual overrides system (`manual_overrides.json` and `manual_override_manager.py`) is strictly designed to correct typographical errors, incorrect specifications, or missing options published in the source PDF brochures by BMW Thailand.
- **No AI Patching:** Do NOT use manual overrides to fix AI extraction or parsing failures. AI errors must be resolved by tuning the prompts or extractor logic, ensuring the AI model extracts what is actually in the PDF as accurately as possible.
- **Comments/Metadata:** All overrides in the JSON file should include a clear reason explaining why the PDF is wrong and what is being corrected. Ignore keys starting with `_` to support comments in JSON.

## 8. Strict TH/EN Specsheet & Image Alignment
- **Identical Structure, Data & Images:** Both specifications and vehicle images (`images` mapping and `image_status`) MUST be 100% identical between the Thai and English databases (`bmw_master_specs.json` vs `bmw_master_specs_en.json`) because both represent the exact same vehicle. The numerical data, option presence/absence (for all topics), topic names, category names, topic counts, category counts, and topic order/positioning must be identical in all aspects between the Thai and English brochures (no swapping, reorganizing, or omitting of categories or topics is permitted).
- **Dual-Language Visual Fingerprint Gate:** When classifying PDF updates, TH and EN must be reconciled as a pair (only when both languages belong to the same update cycle):
  - **Dimensions (`L / W / H`):** Must agree symmetrically across TH and EN. If one language remains unchanged while the other changes, flag `blocked_th_en_conflict`, halt image scraping for that model, and report in the daily email audit.
  - **Wheels:** If EN is unchanged while TH text changed only in Thai wording/spacing (same numeric wheel sizes and English style/code tokens in TH), treat EN as authoritative. If numeric wheel sizes or English tokens in TH also changed, or if TH is unchanged while EN changed, flag `blocked_th_en_conflict`, halt image scraping for that model, and report in the daily email audit.
- **No Bypasses:** Do not build ignore rules or filters for differences in ordering, naming, or TH/EN image mappings. Category grouping mismatches, vehicle-specific engineering differences, and `images` discrepancies must be flagged as active issues for remediation.

## 9. Token & Context Optimization (No Heavy Controlled Vocabulary)
- **No Heavy Dictionaries in Prompts:** Do NOT inject large reference datasets, heavy master dictionaries, or lengthy term lists (e.g., 400+ terms) into LLM prompts. Doing so wastes precious context space, slows down inference, and incurs unnecessary token costs. Rely on targeted few-shot guidance in prompts.
- **Pure Python Post-Processing:** Resolve predictable OCR errors, typographical quirks, and formatting issues through deterministic Pure Python healing rules (Stage 4) rather than dumping large reference datasets.

## 10. Pure Generic Architecture (No Model-Specific Code)
- **Model-Agnostic Design:** All feature creation, improvements, and bug fixes in the extraction, harmonizing, parsing, and post-processing pipeline MUST be model-agnostic and generic across all BMW models.
- **No Hardcoded Model Exceptions:** It is strictly forbidden to hardcode model-specific patches, conditions, or exceptions in the codebase (such as `if "X7-..." in source_pdf_path:` or checking for specific model identifiers) to fix an error for a single car model.
- **Separation of Concerns:** Genuine source PDF typographical errors or omissions published by BMW Thailand belong strictly in `manual_overrides.json`, while extractor and parser logic must remain universally robust and applicable to all models.
