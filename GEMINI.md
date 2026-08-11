# Project Context
BMW Dynamic Specsheet: Extracting tech specs from PDFs into JSON, and displaying them on an HTML frontend.

# Core Rules (STRICTLY ENFORCED)
1. **JSON Structure:** Keys MUST be in snake_case English. Values will be mixed Thai/English. DO NOT translate or hallucinate any data.
2. **Matrix Data (■):** The "■" symbol indicates an option match. Map it correctly to the column header.
3. **Frontend Search:** The JS search logic must be case-insensitive and support fuzzy matching for mixed Thai-English keywords.
4. **No Code Breakage:** Ensure existing column toggle functions in index.html remain intact when adding new features.
5. **Manual Overrides Purpose:** The manual overrides system is strictly designed to correct typographical errors, incorrect specifications, or missing options in the source PDF brochures published by BMW Thailand. It is NOT for correcting AI extraction failures (AI extraction should be accurate to the PDF content).
6. **Strict TH/EN Specsheet Alignment:** The numerical data, option presence/absence (for all topics), topic names, category names, topic counts, category counts, and topic order/positioning must be identical in all aspects between the Thai and English brochures. No swapping, reorganizing, or omitting of categories or topics is permitted.
7. **Scope and Authorization:** If any proposed work is not explicitly within the scope of the user's instructions, you MUST report the situation and obtain explicit user permission first. Unauthorized modifications or background tasks are strictly prohibited to prevent wasting resources (API quota, CPU/GPU processing, time) and to maintain system reliability.
8. **Targeted Execution Scope:** NEVER run full-database or global scripts (such as auditing all models using `run_production_validation.py`) when testing or verifying a specific model change. Always write targeted, small-scope check scripts or directly query the database to verify changes within 2 minutes.
9. **Time and Resource Estimations:** Before running any command or proposal that is expected to take over 2 minutes or consume significant API quota, the agent must estimate the run time, explain API usage, and seek explicit user confirmation.