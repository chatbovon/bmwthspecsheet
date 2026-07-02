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
