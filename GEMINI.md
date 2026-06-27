# Project Context
BMW Dynamic Specsheet: Extracting tech specs from PDFs into JSON, and displaying them on an HTML frontend.

# Core Rules (STRICTLY ENFORCED)
1. **JSON Structure:** Keys MUST be in snake_case English. Values will be mixed Thai/English. DO NOT translate or hallucinate any data.
2. **Matrix Data (■):** The "■" symbol indicates an option match. Map it correctly to the column header.
3. **Frontend Search:** The JS search logic must be case-insensitive and support fuzzy matching for mixed Thai-English keywords.
4. **No Code Breakage:** Ensure existing column toggle functions in index.html remain intact when adding new features.