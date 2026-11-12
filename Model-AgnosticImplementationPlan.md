# Model-Agnostic PDF Update Classification Implementation Plan

> **Purpose:** แผนสำหรับใช้ดำเนินการใน worktree ใหม่ (แตกจาก local `main`) เพื่อสร้างระบบจำแนกสถานะการอัปเดต PDF เป็น **4 เคสอัตโนมัติ (Pure Python, Model-Agnostic 100%)** พร้อม **Dual-Language Reconciliation Gate (TH/EN 100% Alignment)** และอัปเดตระบบตรวจสอบ/แจ้งเตือนอีเมลใน `send_daily_report.py` จากนั้นทดสอบจำลองผลบนข้อมูลจริงของ **`740d xDrive M Sport`** กับ **`M760e xDrive`** โดย **ยังไม่รัน/ยังไม่แก้ `auto_image_scraper.py`** และ **ยังไม่แก้ไขฐานข้อมูลจริง** จนกว่าจะตรวจผลและได้รับอนุมัติขั้นถัดไป

---

## 0. Baseline State Already Included in Local `main`

ก่อนเริ่ม worktree ใหม่ ระบบบน local `main` มีสถานะฐานข้อมูลและโค้ดพื้นฐานล่าสุดดังนี้:

1. **Databases (`bmw_master_specs.json`, `bmw_master_specs_en.json`)**:
   - มีทั้งสิ้น **34 active entries** (TH/EN ตรงกันครบ, `is_custom_archived: false` สำหรับ `740d xDrive M Sport` [`7-20261014-01`], `M760e xDrive` [`7-20261015-01`] และ `i7 50 xDrive M Sport` [`i7-20261006-03`])
   - ผลตรวจสอบความสอดคล้อง TH/EN ด้วย `send_daily_report.audit_data_discrepancies`: `checks=4078, issues=0`
   - ผลตรวจสอบรูปภาพ (`send_daily_report.audit_missing_images`): **31/33 Non-M models** (ขาดรูปเฉพาะ 2 รุ่น LCI คือ `740d xDrive M Sport` และ `M760e xDrive`)
2. **Scraper & Circuit Breakers (`pdf_scraper.py`, `sync_database.py`, `scratch/archive_discontinued.py`)**:
   - `pdf_scraper.py` มี `collect_unique_pdf_links` และ `is_marketing_brochure` กรองทั้งชื่อไฟล์และข้อความบนลิงก์ (`"โบรชัวร์"`, `"Brochure"`, `"Catalog"`, `"Leaflet"`) ทำให้หน้าเว็บจริง TH/EN คัดได้ **34 specsheets ตรงกับฐานข้อมูล 100%** พร้อม Circuit Breaker ป้องกันการ archive หากโหลดหน้าเว็บไม่ครบ
3. **Frontend UI (`index.html`, `custom.html`)**:
   - แสดงแถว `"รูปภาพตัวอย่าง"` / `"Vehicle Preview"` ต่อท้ายหมวด `Paintwork` ผ่าน `renderVehiclePreviewSection`

---

## 1. Strict Constraints & Workspace Rules

งานทั้งหมดใน worktree ใหม่ต้องยึดตามกฎหลักใน `AGENTS.md` และ `GEMINI.md`:

- **Rule 10 (`AGENTS.md`) / Rule 12 (`GEMINI.md`) — Pure Generic Architecture:** ห้ามเขียนเงื่อนไขระบุชื่อรุ่นรถใดๆ (`if "740d" ...`, `if "M760e" ...`, `if "i7" ...`) ลงในโค้ด classifier / pipeline เด็ดขาด ชื่อรุ่น `740d` และ `M760e` ใช้เป็นเพียงข้อมูลทดสอบ (test verification targets) เท่านั้น
- **Rule 8 (`AGENTS.md`) / Rule 10 (`GEMINI.md`) — Strict Plan-to-Code Fidelity:** Implement ตาม Stage 1 → 2 → 3 → 4 แบบ 1:1 ห้ามรวบขั้นหรือข้ามขั้นตอน
- **Rule 9 (`AGENTS.md`) / Rule 11 (`GEMINI.md`) — Zero Heavy Controlled Vocabulary:** ใช้ Pure Python deterministic normalization เท่านั้น ไม่เรียก LLM API และไม่ฝัง dictionary ขนาดใหญ่
- **Rule 6 (`GEMINI.md`) / Rule 7 (`AGENTS.md`) — Strict TH/EN Specsheet & Image Alignment:** ทั้งข้อมูลสเปค, `images`, และ `image_status` ของ TH และ EN ต้องตรงกัน 100% หากเกิดความขัดแย้งของ Visual Fingerprint (มิติเปลี่ยนฝั่งเดียว หรือล้อฝั่ง TH คงเดิมแต่ EN เปลี่ยน / ขนาดและรหัสล้อขัดแย้งกัน) ต้องหยุดดึงรูปสีเฉพาะรุ่นนั้น (`blocked_th_en_conflict`) และรายงานในอีเมลทันที
- **Scope Boundary (Explicit User Instruction):** **ไม่รันและไม่แก้ไขระบบดึงรูปสี (`auto_image_scraper.py`) ในเฟสนี้** — เน้นเฉพาะระบบจำแนกสถานะ PDF 4 เคส + Dual-Language Reconciliation Gate + integration การ carry-over/hold รูป + การตรวจ/แจ้งเตือนอีเมลใน `send_daily_report.py` + การทดสอบแบบ non-destructive dry-run (ส่วนการให้ `auto_image_scraper.py` ข้าม `blocked_th_en_conflict` และรองรับ `Spec Guard` / `pending_configurator` อยู่ในเฟสถัดไป Section 4)

---

## 2. Real Data Characteristics Observed in Catalog

จากการตรวจสอบไฟล์จริง `bmw_master_specs*.json` และ `bmw_custom_specs*.json` พบข้อเท็จจริงสำคัญที่ต้องออกแบบรองรับแบบ generic:

1. **Lineage Across Master & Custom Archives:**
   - รุ่นก่อนหน้าของ PDF ที่เพิ่งอัปเดตอาจไม่ได้อยู่ใน `bmw_master_specs*.json` แล้ว แต่อาจถูกย้ายไปเก็บใน `bmw_custom_specs*.json`
   - ตัวอย่างจริง: `M760e xDrive` (`7-20261015-01`, `images: []`) มีรุ่นก่อนหน้าชื่อเดียวกันเป๊ะ (`M760e xDrive`, `7-20250130-02`, มีรูปครบ 4 สี) อยู่ใน `bmw_custom_specs*.json`
2. **Real-World Typo & Formatting Variations in Visual Fingerprint Fields:**
   - **Dimensions (`Length / width / height (mm)`)**:
     - หมวด: `มิติรถยนต์` (TH) / `DIMENSION` / `Dimension` (EN)
     - ชื่อหัวข้อใน PDF ไทยบางฉบับมีคำสะกด `'มิตรถยนต์ ยาว/กว้าง/สูง (มิลลิเมตร)'` แทน `'มิติรถยนต์ ยาว/กว้าง/สูง (มิลลิเมตร)'` → ควรจับจาก substring `'ยาว/กว้าง/สูง'` (TH) หรือ `'length / width / height'` (EN) ภายในหมวดมิติรถยนต์
     - ค่าตัวเลขมีรูปแบบคอมม่า/เว้นวรรคต่างกัน (เช่น `'5,391 / 1,950 / 1,544'` vs `'5395 / 1950 / 1558'`)
   - **Wheels (`Light alloy wheels` / `Wheels` / `ล้อ`)**:
     - หมวด: `ล้อและยาง` (TH) / `WHEELS AND TYRES` / `Wheels and Tyres` (EN) — **ต้องกรองเฉพาะในหมวดล้อและยาง** เพื่อไม่ให้สับสนกับพวงมาลัย (`Steering wheel`) ในหมวด `Interior`
     - หัวข้อ: `'ล้อ'` (TH) หรือ `'Wheels'` / `'Light alloy wheels'` (EN)
     - สัญลักษณ์นิ้วมีทั้ง double apostrophe `''` (เช่น `20''`) และ double quote `"` (เช่น `21"`) รวมถึงเว้นวรรคติดกัน (เช่น `aerodynamicขนาด`)

---

## 3. Target 4-Stage Implementation Architecture

### Stage 1: Model-Agnostic Lineage Resolver (`pdf_update_classifier.py`)

สร้างฟังก์ชันค้นหารุ่นก่อนหน้าแบบ generic จากทั้ง `master_specs` และ `custom_specs`:

- `normalize_series_name(series_name: str) -> str`: normalize ชื่อซีรีส์ (เช่น `"BMW 7 SERIES"` == `"BMW 7 Series"` → `"bmw 7 series"`)
- `normalize_model_name(model_name: str) -> str`: normalize ชื่อรุ่นแบบ case-insensitive / whitespace-collapsed (เช่นตัดช่องว่างเกิน, รองรับอักขระ `é`/`e`)
- `extract_doc_date_sort_key(pdf_source: str) -> tuple`: ใช้เรียงลำดับความใหม่ของ predecessor ในกรณีพบหลายรายการใน archive (เลือกฉบับล่าสุดที่มีข้อมูลครบและไม่ใช่ `pdf_source` เดียวกันกับ candidate ถ้าเป็นการอัปเดตข้ามไฟล์)
- `find_predecessor_lineage(candidate_entry, candidate_model, master_specs, custom_specs)`:
  - จับคู่แบบ **Strict Matching** ด้วย `(normalized_series, normalized_model_name)`
  - หากไม่พบ exact match ให้เก็บ `closest_series_models` (รุ่นอื่นในซีรีส์เดียวกันที่อาจใกล้เคียงเชิงชื่อ/ตัวเลข เช่น `740d M Sport` สำหรับ `740d xDrive M Sport`) ไว้ใน metadata เฉยๆ **ห้ามนำมาจับคู่เป็น minor update เพื่อยืมรูปข้ามรุ่นย่อยเด็ดขาด**

### Stage 2: Pure Python Visual Fingerprint Extractor & Comparator (`pdf_update_classifier.py`)

ดึงลายนิ้วมือรูปลักษณ์ภายนอกแบบ deterministic สำหรับทุกรุ่น:

- `normalize_dimensions_value(raw_value: str) -> str`: สกัดเลข 3 ค่า `L / W / H` ด้วย regex ตัวเลข (ตัด `,` และช่องว่าง) → คืนค่ามาตรฐาน เช่น `"5391/1950/1544"`
- `normalize_wheels_value(raw_value: str) -> str`: แปลง `''` / `“` / `”` → `"`, lowercase, แทรกช่องว่างตรงรอยต่ออักษรละติน/ตัวเลขกับอักษรไทย (เช่น `aerodynamicขนาด` → `aerodynamic ขนาด`), และ collapse whitespace
- `extract_wheel_core_signature(raw_value: str) -> dict`: สกัดข้อมูลแกนหลักของล้อแบบ Pure Python regex (ไม่มี dictionary ขนาดใหญ่) ได้แก่ **ตัวเลขขนาดนิ้วล้อ** (เช่น `["18"]` หรือ `["19", "20"]`) และ **token ตัวอักษร/รหัสภาษาอังกฤษ** (เช่น `double-spoke`, `909`, `m`, `bicolour`) เพื่อใช้ตรวจสอบใน Dual-Language Gate ว่าการเปลี่ยนฝั่ง TH เป็นเพียงการแก้คำ/เว้นวรรคภาษาไทยหรือเปลี่ยนสเปคขนาด/รหัสล้อจริง
- `extract_visual_fingerprint(model: dict) -> dict`:
  - ดึง `dimensions`, `wheels`, และ optional `powertrain_output` (เพื่อแสดงในรายงาน diff เชิงตรวจสอบ)
  - บังคับตรวจเฉพาะหมวด `มิติรถยนต์` / `dimension` และ `ล้อและยาง` / `wheels` เท่านั้น
- `compare_visual_fingerprints(old_fp: dict, new_fp: dict) -> dict`:
  - เปรียบเทียบทั้ง `dimensions` และ `wheels`
  - **Fail-safe guard:** หาก `dimensions` หรือ `wheels` ของฝั่งเก่าหรือฝั่งใหม่ **ว่าง/หาไม่พบ (`missing_fields`)** ให้ถือว่าไม่สามารถยืนยันความเหมือนโฉมได้ (ห้ามจัดเป็น Case 2 `MINOR_UPDATE` เพื่อป้องกันการคัดลอกรูปผิดโฉมโดยไม่ตั้งใจ)

### Stage 3: 4-Case Decision Matrix & Pipeline Integration

#### 4 Automated Classification Cases (`classify_model_update` / `classify_brochure_update`)

| Case ID | Case Name | Status / Action | Deterministic Condition (Pure Python) | Image Carry-over Behavior |
| :--- | :--- | :--- | :--- | :--- |
| **1** | `IDENTICAL` | `smart_skipped` | พบ predecessor และไฟล์ PDF มี `pdf_sha256` หรือข้อความหลัง normalize (`verify_pdf_content.extract_normalized_text`) เหมือนกัน 100% | ใช้ข้อมูลและ `images` เดิม 100%, ข้าม AI extraction |
| **2** | `MINOR_UPDATE` | `reused_same_gen` | พบ exact lineage predecessor, เนื้อหา PDF เปลี่ยน (หรือไม่ทราบ PDF เก่าแต่คนละไฟล์), และ **Visual Fingerprint ตรงกัน 100%** (ทั้ง `dimensions` และ `wheels` ครบและเท่ากัน) | **Reuse `images` เดิมอัตโนมัติ** เฉพาะสีที่มีอยู่ในโมเดลใหม่ (ผ่านสี normalized match) |
| **3** | `LCI_OR_VISUAL_CHANGE` | `lci_refresh_required` | พบ exact lineage predecessor แต่ `dimensions` เปลี่ยน **หรือ** `wheels` เปลี่ยน (หรือ fail-safe เมื่อ fingerprint ไม่ครบ) | **ห้าม reuse รูปเก่าอัตโนมัติ** ตั้ง `images: {}` และเก็บ `visual_diff` / `previous_images_count` ไว้ในผลลัพธ์ |
| **4** | `BRAND_NEW` | `new_model_scrape` | ไม่พบ exact `(series, model_name)` ใน `master_specs` และ `custom_specs` | ตั้ง `images: {}` (แนบ `closest_series_models` ในผลวินิจฉัยถ้ามี) |

#### Dual-Language Reconciliation Gate (`reconcile_th_en_updates`)
เนื่องจากใน `.github/workflows/auto_update.yml` ขั้นตอน `batch_extractor.py --lang th` รันก่อน `--lang en` (ตอน TH รันเสร็จยังไม่มีสเปค EN ใหม่) จึงต้องมีขั้นตอน **Dual-Language Reconciliation Gate** ทำงานหลังสกัดครบทั้ง TH และ EN (ก่อน `auto_image_scraper.py` และ `send_daily_report.py`) เพื่อบังคับให้ TH และ EN มี `images` และ `image_status` **ตรงกัน 100%**:

1. **Paired-Cycle Check:** ตรวจสอบว่า TH และ EN อัปเดตเป็นคู่ฉบับรอบเดียวกัน (เทียบ document date / `pdf_source` ของ TH vs EN) หากวันนั้นมีโบรชัวร์ใหม่อัปโหลดเข้ามาเพียงภาษาเดียว (อีกภาษายังเป็นไฟล์เก่าจากรอบก่อน) ให้ติดสถานะ `pending_paired_language` (ไม่ถือว่า EN เก่าที่ยังไม่อัปเดตเป็นการยืนยัน `EN_old == EN_new`) และแจ้งเตือนในรายงาน
2. **Dimensions Rule (Symmetric Conflict Check):**
   - มิติรถยนต์ (`L / W / H`) เป็นตัวเลขล้วน ต้องตรงกันทั้ง TH และ EN (`EN_unchanged == TH_unchanged`)
   - หากฝั่งหนึ่งเท่าเดิมแต่อีกฝั่งเปลี่ยน (`EN_old == EN_new` แต่ `TH_old != TH_new` **หรือ** `TH_old == TH_new` แต่ `EN_old != EN_new`) → จัดเป็น **`blocked_th_en_conflict`** (หยุดดึงรูปสีเฉพาะรุ่นนั้นทันที และส่ง Alert ในอีเมลเพื่อแก้ปัญหา)
3. **Wheels Rule (Authoritative EN + TH Core-Spec Guard):**
   - **`EN_old == EN_new` แต่ `TH_old != TH_new`:** ใช้ `extract_wheel_core_signature` ตรวจเทียบ **ตัวเลขขนาดนิ้ว + token/รหัสภาษาอังกฤษ** ของ TH เก่า vs TH ใหม่:
     - หากขนาดนิ้วและรหัสภาษาอังกฤษใน TH ตรงกัน 100% (ต่างกันเฉพาะคำบรรยายไทย/คำสะกด/เว้นวรรค) → **ให้ถือ EN เป็นหลัก** (`wheels_match = True`, เข้า Case 2 `reused_same_gen` หากมิติตรงกันด้วย และบันทึก audit note)
     - หากขนาดนิ้วหรือรหัสภาษาอังกฤษใน TH เปลี่ยนด้วย → จัดเป็น **`blocked_th_en_conflict`** (สงสัยว่า EN ลืมอัปเดตหรือสกัดผิด: หยุดดึงรูปสีเฉพาะรุ่นนั้นและแจ้ง Alert ในอีเมล)
   - **`TH_old == TH_new` แต่ `EN_old != EN_new`:** ผิดปกติ → จัดเป็น **`blocked_th_en_conflict`** (หยุดดึงรูปสีเฉพาะรุ่นนั้นและแจ้ง Alert ในอีเมล)
4. **100% Image & Status Sync:** เขียน `images` และ `image_status` (`reused_same_gen`, `lci_refresh_required`, `new_model_scrape`, `blocked_th_en_conflict`, หรือ `pending_paired_language`) ให้ตรงกัน 100% ทั้งใน `bmw_master_specs.json` และ `bmw_master_specs_en.json`

#### Files to Integrate in Stage 3
1. **Create `pdf_update_classifier.py`**:
   - รวม Stage 1 + Stage 2 + Stage 3 classifier + `reconcile_th_en_updates` (Dual-Language Gate) + CLI dry-run analyzer (`python pdf_update_classifier.py --dry-run --lang all`) และโหมด `--reconcile-th-en` สำหรับทำงานหลัง extraction ครบทั้ง 2 ภาษา
   - Output ระดับทั้งรุ่น (per-model) และสรุประดับไฟล์ PDF (per-brochure) เพื่อรองรับโบรชัวร์ที่มีหลายรุ่นย่อยในไฟล์เดียว
2. **Update `verify_pdf_content.py` (`L89-L228`)**:
   - คง behavior เดิมของ `smart_skipped` (Case 1) เป็นด่านแรก และเพิ่มตัวช่วยหา predecessor ผ่าน lineage / normalized text สำหรับกรณีชื่อไฟล์/วันที่เปลี่ยนไปจากเดิม (แทนที่การเทียบ `new_base == old_base` อย่างเดียว)
3. **Update `batch_extractor.py` (`L122-L138`)**:
   - เปลี่ยน logic เดิม (`old_entry = next((item for item in master_specs if item.get("pdf_source") == filename), None)`) ให้เรียก `pdf_update_classifier` เทียบกับทั้ง `master_specs` และ `custom_specs` (TH/EN ตามภาษา):
     - `Case 2 (reused_same_gen)` → คัดลอก `images` ที่สีตรงกันจาก predecessor พร้อมอัปเดต `"image_status": "reused_same_gen"`
     - `Case 3 (lci_refresh_required)` → กำหนด `"images": {}`, `"image_status": "lci_refresh_required"`
     - `Case 4 (new_model_scrape)` → กำหนด `"images": {}`, `"image_status": "new_model_scrape"`
   - **หมายเหตุ:** ยังไม่แตะ `auto_image_scraper.py` และไม่รันสคริปต์ดึงรูปสี (แต่ให้รองรับการเรียก `reconcile_th_en_updates` หลังสกัดครบทั้ง TH และ EN เพื่อ sync `images` / `image_status` ให้ตรงกัน 100%)
4. **Update `send_daily_report.py` (`audit_data_discrepancies` & `generate_html_report`)**:
   - เพิ่มการตรวจเทียบ `images` และ `image_status` ระหว่าง TH กับ EN ใน `audit_data_discrepancies` (ไม่ให้มี `images` discrepancy หลุดรอด)
   - เพิ่มหมวด Alert ในอีเมลสำหรับรุ่นที่ติด `blocked_th_en_conflict` (มิติเปลี่ยนฝั่งเดียว หรือ ล้อ TH คงเดิมแต่ EN เปลี่ยน / ขนาดและรหัสล้อขัดแย้งกัน) และ `pending_paired_language` เพื่อให้ตรวจสอบและแก้ไขก่อนดึงรูปสี

### Stage 4: Verification & Real-Catalog Test (`740d` & `M760e`)

1. **Unit Tests (Isolated, Zero API Calls)**:
   - ทดสอบครบทั้ง 4 เคส (`IDENTICAL`, `MINOR_UPDATE`, `LCI_OR_VISUAL_CHANGE`, `BRAND_NEW`)
   - ทดสอบ edge cases:
     - สัญลักษณ์นิ้ว `20''` vs `20"`
     - คำสะกด `'มิตรถยนต์ ยาว/กว้าง/สูง (มิลลิเมตร)'` vs `'มิติรถยนต์ ยาว/กว้าง/สูง (มิลลิเมตร)'`
     - Missing dimension/wheel field → fail-safe ไม่หลุดเป็น Case 2
     - Predecessor อยู่ใน `custom_specs` (archived)
     - Multi-model brochure (เช่นหนึ่งรุ่นเป็น Minor Update อีกรุ่นเป็น New Model)
     - Dual-language Dimensions conflict (EN เท่าเดิมแต่ TH เปลี่ยน และ TH เท่าเดิมแต่ EN เปลี่ยน → `blocked_th_en_conflict`)
     - Dual-language Wheels: EN เท่าเดิม + TH เปลี่ยนเฉพาะคำ/เว้นวรรคไทย (`aerodynamicขนาด` vs `aerodynamic ขนาด`, `นี้ว` vs `นิ้ว`) → ถือ EN เป็นหลัก (`MINOR_UPDATE` / `reused_same_gen`)
     - Dual-language Wheels: EN เท่าเดิม + TH เปลี่ยนตัวเลขขนาดนิ้ว/รหัสลายล้อ → `blocked_th_en_conflict`
     - Dual-language Wheels: TH เท่าเดิม + EN เปลี่ยน → `blocked_th_en_conflict`
     - Unpaired update cycle (อัปเดตมาแค่ภาษาเดียว) → `pending_paired_language`
     - `send_daily_report.audit_data_discrepancies` ตรวจจับ `images` / `image_status` mismatch ระหว่าง TH กับ EN ได้ครบถ้วน
2. **Real-Catalog Dry-Run Check (`TH` และ `EN` — No File Writes)**:
   - ทดสอบรัน `pdf_update_classifier` จำลองเทียบ `bmw_master_specs*.json` กับ `bmw_custom_specs*.json` (excluding exact same `pdf_source` entry เพื่อให้เห็นผลเมื่อรุ่นนั้นถูกอัปเดตเข้ามา)
   - ยืนยันผลเฉพาะจุดสำหรับ:
     - **`M760e xDrive` (`7-20261015-01`)**: ต้องจัดเข้า **Case 3 (`lci_refresh_required`)** โดยจับคู่กับ `7-20250130-02` ใน `bmw_custom_specs*.json` และตรวจพบทั้ง **dimensions** (`5391/1950/1544` → `5395/1950/1550`) และ **wheels** ที่เปลี่ยนไป
     - **`740d xDrive M Sport` (`7-20261014-01`)**: ต้องจัดเข้า **Case 4 (`new_model_scrape`)** ภายใต้ strict model lineage (และแสดง `closest_series_models` ชี้ไปยัง `740d M Sport` ที่มี delta มิติ/ล้อ `5391/1950/1544` → `5395/1950/1550`, ล้อ `20"` → `21"`)
   - ทดสอบรุ่นอื่นๆ ที่มีประวัติเทียบเคียงได้ใน `master` vs `custom` (เช่น `iX1 eDrive20L M Sport`, `X7 xDrive40d M Sport`, `i5 eDrive40 M Sport`, `M5 Touring`, `220 Gran Coupe M Sport Pro`, `M3 Competition M xDrive Touring`) เพื่อตรวจว่า Case 2 และ Case 3 แยกแม่นยำจริงทั้ง TH และ EN
   - **Rule 8 Verification Compliance:** ไม่รัน `run_production_validation.py` และไม่รัน `batch_extractor.py` แบบยิง Gemini API จริง

---

## 4. Future Phase (Deferred — Out of Current Worktree Scope Unless Separately Approved)

หลังจากได้ผลทดสอบ 4 เคสจาก Stage 4 เรียบร้อยแล้ว ค่อยพิจารณาอนุมัติในรอบถัดไป:
- อัปเดต `auto_image_scraper.py`:
  - ข้ามรุ่นที่ติด `blocked_th_en_conflict` หรือ `pending_paired_language` (หยุดดึงรูปสีอัตโนมัติจนกว่า conflict จะถูกแก้)
  - เพิ่ม `Spec Guard` (เช็กแรงม้า/สเปคบน Configurator เทียบกับ specsheet เพื่อป้องกันรุ่น LCI ชื่อเดิมไปดูดรูป Pre-LCI เก่า) และสถานะ `pending_configurator` เมื่อ Configurator ยังไม่มีรุ่น/โฉมใหม่ (เพื่อให้รอบวันถัดไปกลับมาลองดึงใหม่อัตโนมัติทันทีที่ BMW เปิดตัวบน Configurator)
- อัปเดต `send_daily_report.py` แยกกลุ่ม `pending_configurator` vs `broken` ในอีเมล `Image Coverage`
- อัปเดต `.github/workflows/auto_update.yml`:
  - เรียกขั้นตอน Dual-Language Reconciliation (`python pdf_update_classifier.py --reconcile-th-en`) หลังจบ `batch_extractor.py --lang th` และ `--lang en` (ก่อน `auto_image_scraper.py`)
  - แก้บรรทัด `146` จาก `git add -f images/**/*.png` ให้ครอบคลุม `images/**/*.webp` ด้วย
