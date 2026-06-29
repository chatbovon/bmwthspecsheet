# BMW Dynamic Specsheet — Handover Log

**Last Updated:** 29 June 2026, 13:30 (ICT)  
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
                            [NEW] Routes dual-PDF pairs through page-by-page extractor
                            [NEW] scan_model_header_page() — column-to-model mapping
                            [NEW] build_page_prompt()      — per-page prompt injection
                            [NEW] merge_page_results()     — JSON deep-union merger
                            [NEW] extract_pdf_page_by_page() — orchestrator
                            [NEW] _extract_page_with_retry() — per-page API caller
page_splitter.py         <- [NEW] PDF splitting utility (requires: pip install pypdf)
                            split_all_pages(), extract_single_page(), cleanup_temp_pages()
prompt_validation_th.py  <- Prompt library (TH single + TH/EN dual validated)
scratch/tmp_pages/th/   <- [NEW] Temp dir for single-page TH PDFs (auto-cleaned)
scratch/tmp_pages/en/   <- [NEW] Temp dir for single-page EN PDFs (auto-cleaned)
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
- 3 keys registered: `GEMINI_API_KEY_1` through `GEMINI_API_KEY_3`
- Automatic rotation on rate limit (RPM -> wait 20s, RPD exhausted -> rotate key)
- If a model exhausts daily quota across ALL keys -> skip to next model in chain

---

## 3. Completed Work

| # | Task | Status |
|---|---|---|
| 1 | Extract specs from all 37 PDF brochures | COMPLETE |
| 2 | API Key Pooling (3 keys, auto-rotation) | COMPLETE |
| 3 | Model chain fallback (no lite models) | COMPLETE |
| 4 | Paintwork matrix formatting (Exterior -> Seat Leather/Material) | COMPLETE |
| 5 | Footer References extraction (date + local pack codes) | PARTIAL (see flags) |
| 6 | Resume capability (skip already-processed files) | COMPLETE |
| 7 | Cross-lingual validation (TH + EN dual PDF mode) | COMPLETE |
| 8 | Hardest files (3 sub-models) processed first | COMPLETE |
| 9 | Web frontend (index.html) with search & column toggle | COMPLETE |
| 10 | GitHub repo changed to Private | COMPLETE |
| 11 | Page-by-Page Dual-PDF extraction (timeout prevention) | **COMPLETE** |

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
| batch_extractor.py | Extraction engine (now with page-by-page mode) |
| page_splitter.py | PDF splitting utility (new dependency: pypdf) |
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
| scratch/tmp_pages/ | Auto-generated single-page temp PDFs (always cleaned up) |
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
| 3-key pooling | Single key has RPD=20; 3 keys = up to 60 RPD per model |

---

## [Update: 2026-06-29] Architecture Corrections & Gemini 3.1 Flash Lite Testing

**1. Project Environment & Configuration Updates:**
* โครงสร้างการทำงานปัจจุบันถูกแยกเป็นอิสระผ่าน Git Worktree บนสาขา `implement-page-batch-extraction` เพื่อให้มั่นใจว่าไฟล์หลักจะไม่ถูกกระทบ.
* ตรวจสอบพบว่าโค้ดใน `batch_extractor.py` มีการตั้งค่าตัวแปรเพื่อรับ API Key เพียง 3 ตัว (`GEMINI_API_KEY_1`, `2`, `3`) ไม่ใช่ 4 ตัวตามที่เคยบันทึกไว้[cite: 2].

**2. Testing Gemini 3.1 Flash Lite & Hallucination Discovery:**
* มีการทดลองใช้โมเดล `gemini-3.1-flash-lite` ร่วมกับระบบ Page-by-page เพื่อประหยัดโควต้า[cite: 2].
* ผลการทดสอบกับไฟล์ 3 Series พบว่าโมเดลสกัดข้อมูลโครงสร้างได้ครบถ้วน แต่เกิดการ "มโนข้อมูล" (Hallucination) โดยระบุว่ารุ่น 320d M Sport (ซึ่งเป็นเครื่องยนต์ดีเซล) มีออปชัน "BMW Iconic sounds electric" เป็น "■"[cite: 2].
* มีการรันทดสอบโหมดภาษาอังกฤษ (EN) เพื่อทำ Cross-validation แต่ระบบไม่สามารถแจ้งเตือนข้อผิดพลาดนี้ได้ (ไม่มี flag)[cite: 2].
* สาเหตุที่ระบบไม่แจ้งเตือน เป็นเพราะโมเดล Lite สกัดข้อมูลผิดพลาดในจุดเดียวกันทั้งฝั่ง TH และ EN เมื่อนำผลลัพธ์มาเทียบกัน ระบบจึงเข้าใจผิดว่าข้อมูลนั้นถูกต้องแล้ว[cite: 2].
* ข้อสรุป: โมเดล Lite มีขีดความสามารถไม่เพียงพอสำหรับงานที่ต้องวิเคราะห์ข้อมูลซับซ้อนพร้อมกับการตรวจสอบความถูกต้องข้ามภาษาในบริบทเดียวกัน[cite: 2].

**3. Final Implemented Solutions (Accuracy over API Cost):**
* **Temperature = 0:** ปรับตั้งค่า `config={"temperature": 0}` ในโค้ดทุกจุด เพื่อลดการสุ่มและบังคับให้ AI อ้างอิงข้อมูลตามไฟล์เอกสารอย่างเคร่งครัด[cite: 2].
* **Per-Column Extraction:** เปลี่ยนสถาปัตยกรรมจากการสกัดทีละหน้า เป็นการสกัดทีละคอลัมน์ (รุ่นย่อย) แทน เพื่อลดขนาดบริบทข้อมูลและแก้ปัญหาการสลับคอลัมน์[cite: 2].
* ระบบ Per-Column จะใช้จำนวน API Call เพิ่มขึ้น (เช่น ไฟล์ที่มีรถ 3 รุ่น จะใช้ 13 API Calls) แต่สามารถรองรับได้ด้วยโควต้า 1,500 Requests/วัน จาก API Key ทั้ง 3 ตัว[cite: 2].


*End of Handover Log*
