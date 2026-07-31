# Workspace Rules: BMW Dynamic Specsheet

## 1. API Keys & Environments
- **3 API Keys Configured:** The project utilizes 3 Gemini API keys for pooling and rate limit rotation: `GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`, and `GEMINI_API_KEY_3`.
- **Dynamic Loading Required:** Always load API keys dynamically from the `.env` file in the workspace root. **NEVER hardcode API keys** in Python scripts or environment variables during testing.
- **MinerU API Token:** Always load `MINERU_API_TOKEN` dynamically from the `.env` file.

## 2. Models Setup
- **QA validation script:** Use `gemini-3.5-flash` as primary, with `gemini-3.1-flash-lite` and `gemini-2.5-flash` as fallbacks.
- **Extraction script:** Use `gemini-3.5-flash` as primary, with `gemini-3.1-flash-lite` and `gemini-2.5-flash` as fallbacks.

## 3. PDF Table Grouping Constraints
- **At Most 5 Pages:** BMW PDF brochures are at most 5 pages.
- **Segment Limit:** The table splitting logic must group tables to output at most 2 or 3 segments per PDF.
- **Size Threshold:** Combine small adjacent tables together up to ~7,000 characters per segment. This drastically reduces API calls, prevents rate limit exhaustion, and keeps the output well within Gemini's token limits.

## 4. Planning & Modification Approval
- **Always Plan First:** Before making any modifications to the codebase (no matter how minor or simple they are), you must present a detailed implementation plan and obtain the user's explicit approval first. Do not make changes without permission.

## 5. Future Roadmap
- **Invalid API Key Notification System:** Integrate a notification system (e.g., Discord/Slack webhook or LINE Messaging API) triggered when `mineru_extractor.py` or validation scripts detect an invalid key (`[REMOVE]`) or hit `[FATAL]` errors. This ensures instant mobile alerts during automated GitHub Actions workflow failures.

## 6. Manual Overrides Design Philosophy
- **PDF-Level Correction:** The manual overrides system (`manual_overrides.json` and `manual_override_manager.py`) is designed solely to correct mistakes inherent in the source PDF brochures (e.g., typos or incorrect specs published by BMW Thailand).
- **No AI Patching:** Do NOT use manual overrides to fix AI extraction or parsing failures. AI errors must be resolved by tuning the prompts or extractor logic, ensuring the AI model extracts what is actually in the PDF as accurately as possible.
- **Comments/Metadata:** All overrides in the JSON file should include a clear reason explaining why the PDF is wrong and what is being corrected. Ignore keys starting with `_` to support comments in JSON.

## 7. Strict TH/EN Specsheet Alignment
- **Identical Structure & Data:** All validation and auditing logic must strictly check that the Thai and English brochures match in all components: numerical values, option presence, category names, topic names, category counts, topic counts, and exact order/position of rows and columns.
- **No Bypasses:** Do not build ignore rules or filters for differences in ordering or naming. Category grouping mismatches and vehicle-specific engineering differences must be flagged as active issues for remediation.
