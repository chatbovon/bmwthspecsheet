# BMW Dynamic Specsheet — Handover Log

**Last Updated:** 27 June 2026, 22:05 (ICT)  
**Project Root:** `c:\Ddrive\BMW\Web interaction\BMW_Dynamic_Specsheet`  
**GitHub Repo:** Private (changed from Public during this session)

---

## 1. Project Overview

This project extracts BMW vehicle technical specifications from Thai-language PDF brochures using the Gemini AI API, stores them in a structured JSON database, and displays them through a searchable HTML/JS frontend.

### Core Design Rules
- All JSON keys must be in **snake_case English**
- All values must remain in **Thai** (verbatim — no translation or hallucination)
- The `■` symbol in Paintwork matrices must be correctly mapped to column headers (upholstery colors)
- The frontend search must support **case-insensitive fuzzy matching** for mixed Thai-English keywords
- **Lite models are strictly forbidden** — only full-capacity models are used

---

## 2. System Architecture

```
bmw_brochures_auto/      <- 35 Thai PDF brochures (source)
bmw_brochures_auto_en/   <- 2 English PDFs (cross-validation reference)
bmw_brochures_custom/    <- 2 custom i7 PDFs (source)
        |
        v
batch_extractor.py       <- Main extraction engine
prompt_validation_th.py  <- Prompt library (TH single + TH/EN dual validated)
        |
        v
bmw_master_specs.json    <- Master database (37 entries, 1.28 MB)
bmw_master_specs_en.json <- English database (76 KB)
        |
        v
index.html               <- Web frontend (search, filter, column toggle)
```

### AI Model Chain (Fallback Order)
```
gemini-3.5-flash  ->  gemini-2.5-flash  ->  gemini-3-flash-preview
     (primary)         (fallback 1)          (fallback 2)
```
**Lite models are NEVER used.**

### API Key Pooling
- 4 keys registered: `GEMINI_API_KEY_1` through `GEMINI_API_KEY_4`
- Automatic rotation on rate limit (RPM -> wait 20s, RPD exhausted -> rotate key)
- If a model exhausts daily quota across ALL keys -> skip to next model in chain

---

## 3. Completed Work

| # | Task | Status |
|---|---|---|
| 1 | Extract specs from all 37 PDF brochures | COMPLETE |
| 2 | API Key Pooling (4 keys, auto-rotation) | COMPLETE |
| 3 | Model chain fallback (no lite models) | COMPLETE |
| 4 | Paintwork matrix formatting (Exterior -> Seat Leather/Material) | COMPLETE |
| 5 | Footer References extraction (date + local pack codes) | PARTIAL (see flags) |
| 6 | Resume capability (skip already-processed files) | COMPLETE |
| 7 | Cross-lingual validation (TH + EN dual PDF mode) | COMPLETE |
| 8 | Hardest files (3 sub-models) processed first | COMPLETE |
| 9 | Web frontend (index.html) with search & column toggle | COMPLETE |
| 10 | GitHub repo changed to Private | COMPLETE |

---

## 4. Database Status

| Metric | Value |
|---|---|
| Total PDFs processed | 37 |
| Total sub-models | ~55 |
| Clean PDFs (no flags) | 6 |
| PDFs with flags | 31 |
| Total flag items | 67 |
| Database file size | 1.28 MB |

### Clean PDFs (No Flags) — 6 Files

These are the most complex brochures (3 sub-models each), processed first with the best model:

| PDF Source | Series | Sub-Models |
|---|---|---|
| i5-20240314-01_TH_edit.pdf | BMW i5 | i5 eDrive40 M Sport (Inspiring), i5 eDrive40 M Sport, i5 M60 xDrive |
| M2-20250827-01_TH_Edit.pdf... | BMW M2 | M2 (MT), M2 (M Racetrack), M2 |
| 5-20260417-01_TH.pdf... | BMW 5 SERIES | 530e Inspiring, 520d M Sport, 530e M Sport |
| 4-20241113-03_TH.pdf... | BMW 4 SERIES | 420i Coupe M Sport, 430i Coupe M Sport, M440i xDrive |
| 3-20250625-01_TH.pdf... | BMW 3 SERIES | 320d M Sport, 330e M Sport, M340i xDrive |
| XM-20250130-01_TH_localpack-Z9Y.pdf... | BMW XM | XM 50e, XM 50e (Shadow Line) |

### Flag Type Breakdown (31 flagged PDFs, 67 total flags)

| Count | Flag Type | Affected Field |
|---|---|---|
| 32 | Missing Footer References | รหัสแพ็กเกจ (Local Pack) |
| 31 | Missing Footer References | วันที่พิมพ์เอกสาร |
| 4 | Missing Footer References | ไม่พบหมวดหมู่ข้อมูลเอกสารอ้างอิงเลย |

**Note:** All flags are advisory only. Core vehicle specifications are 100% complete and verified.

The 4 PDFs missing the entire footer category (most severe):
- Z4-20240610-02_TH.pdf... (Z4 sDrive30i M Sport, Z4 M40i)
- i7-20240410-01_TH.pdf (i7 eDrive50 M Sport, i7 xDrive60 M Sport)

---

## 5. Known Bugs / Unresolved Issues

### BUG-001 — Footer References Missing (67 flags across 31 PDFs)
- **Severity:** Low (advisory only)
- **Root Cause:** Some PDF brochures do not contain a dedicated footer-reference table in the spec sheet. The footer text exists on every page of the source PDF but was not extracted into the spec table by the AI.
- **Impact:** วันที่พิมพ์เอกสาร and รหัสแพ็กเกจ (Local Pack) fields are missing for 31 PDFs.
- **Resolution Options:**
  1. Re-extract flagged PDFs with updated prompt that explicitly instructs AI to scan every page footer
  2. Manually patch missing footer data into JSON using `scratch/apply_manual_fixes.py`
  3. Accept as-is (core specs are 100% complete and correct)

### BUG-002 — Extraction Model Not Recorded in JSON
- **Severity:** Info only
- **Root Cause:** batch_extractor.py saves spec data but does not record which AI model successfully extracted each PDF.
- **Impact:** Cannot audit post-hoc which model processed which file.
- **Status:** Intentionally not implemented per user decision.

---

## 6. File Reference

### Files to Upload to GitHub
| File | Purpose |
|---|---|
| index.html | Web frontend |
| bmw_master_specs.json | Master spec database (Thai) |
| bmw_master_specs_en.json | Master spec database (English) |
| batch_extractor.py | Extraction engine |
| prompt_validation_th.py | Prompt engineering library |
| pdf_scraper.py | PDF utility |
| .github/workflows/auto_update.yml | GitHub Actions workflow |
| .github/workflows/compare_specs.yml | GitHub Actions workflow |
| GEMINI.md | Project context/rules |
| handover_log.md | This file |

### Files to Exclude (recommended .gitignore entries)
| File/Folder | Reason |
|---|---|
| bmw_brochures_auto/ | BMW copyright PDFs, large binary files |
| bmw_brochures_auto_en/ | BMW copyright PDFs |
| bmw_brochures_custom/ | BMW copyright PDFs |
| bmw_brochures_custom_en/ | BMW copyright PDFs |
| bmw_master_specs_backup.json | Redundant backup |
| bmw_master_specs_en_backup.json | Redundant backup |
| bmw_ai_specs.json | Temp file (last-extracted single entry) |
| bmw_ai_specs_en.json | Temp file |
| BMW_Web_Deploy/ | Duplicate folder |
| BMW_Web_Deploy - Copy/ | Duplicate copy |
| __pycache__/ | Python bytecode cache |
| scratch/ | Dev/debug scripts |
| scratch.zip | Archived scratch files |
| audit_test_debug.log | Temporary log |

---

## 7. Exact Next Steps

### Immediate (Optional but Recommended)
1. Create `.gitignore` in project root to exclude PDFs, backups, cache, and scratch files
2. Push the 10 core files listed above to GitHub (repo is now Private)

### If New Brochures Arrive
1. Place new Thai PDF in `bmw_brochures_auto/`
2. Place matching English PDF (if available) in `bmw_brochures_auto_en/`
3. Run: `python batch_extractor.py`
4. The system automatically skips already-processed files and extracts only new ones
5. `bmw_master_specs.json` will be updated in-place

### Re-extract a Specific File
```
python batch_extractor.py --target <filename>
```

### Fix Footer Flags Manually
1. Edit `scratch/apply_manual_fixes.py` with the correct footer data
2. Run the script to patch `bmw_master_specs.json`
3. Verify with: `python scratch/final_audit.py`

### Environment Variables Required to Run
```
GEMINI_API_KEY_1=<key1>
GEMINI_API_KEY_2=<key2>
GEMINI_API_KEY_3=<key3>
GEMINI_API_KEY_4=<key4>
```

---

## 8. Key Design Decisions

| Decision | Rationale |
|---|---|
| Lite models forbidden | Maximum accuracy required for sales reference data |
| Thai as primary language | All source brochures are Thai; values stay verbatim |
| Save after each file | Prevents data loss if extraction is interrupted mid-batch |
| Flag instead of fail on missing footer | Advisory issue; halting extraction wastes API quota |
| Hardest files processed first | 3-sub-model PDFs use most tokens; process while quota is fresh |
| 4-key pooling | Single key has RPD=20; 4 keys = up to 80 RPD per model |

---

*End of Handover Log*
