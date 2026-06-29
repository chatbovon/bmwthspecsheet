"""
pdf_table_extractor.py
======================
Pre-processor for BMW specsheet PDFs.
Uses pdfplumber (text + coordinates) + pypdfium2 (image rendering) to:
  1. Detect column boundaries from header x-positions (pdfplumber)
  2. Detect checkboxes (■) by dark-pixel cluster scanning per column band (image)
  3. Align each checkbox to the correct column using x-coordinate comparison
  4. Build a structured text table for AI semantic interpretation only

This removes the need for AI to perform spatial/layout reasoning.
"""

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image
from dataclasses import dataclass, field
from typing import Optional

# ─── Configuration ────────────────────────────────────────────────────────────
RENDER_SCALE      = 2.0    # 72 dpi × 2 = 144 dpi
DARK_THRESHOLD    = 110    # pixel brightness < this = "dark"
# Calibrated from BMW PDF: CHECK cells have density 0.017-0.038, DASH cells have 0.000
# Using 0.010 as safe threshold well below minimum CHECK density of 0.017
DARK_DENSITY_MIN  = 0.010
# Narrow scan band: ±30pt around column center (avoids neighbor column bleed)
COL_SCAN_HALF_PT  = 30
TOPIC_MAX_X_PT    = 210    # topics are always to the left of this x (PDF points)
MIN_COL_GAP_PT    = 55     # gap larger than this separates two distinct columns


# ─── Data classes ─────────────────────────────────────────────────────────────
@dataclass
class ColumnDef:
    name: str
    center_x_pt: float     # center x in PDF points
    x0_pt: float           # left scanning boundary
    x1_pt: float           # right scanning boundary


@dataclass
class RowData:
    topic: str
    y_top_pt: float
    values: dict = field(default_factory=dict)  # {col_name: "■" | "-"}


# ─── Step 1: Detect column boundaries ─────────────────────────────────────────
def _find_column_breaks(words_sorted_by_x: list) -> list[list]:
    """
    Given a list of words (sorted by x0) from a single header row,
    find natural column breaks by identifying the LARGEST gaps between words.
    Uses a gap histogram approach: gaps > mean + 1.5*std are column separators.
    """
    if not words_sorted_by_x:
        return []

    # Compute inter-word gaps
    gaps = []
    for i in range(1, len(words_sorted_by_x)):
        gap = float(words_sorted_by_x[i]['x0']) - float(words_sorted_by_x[i - 1]['x1'])
        gaps.append(gap)

    if not gaps:
        return [words_sorted_by_x]

    # Threshold: any gap > mean + 1.5*std is a column separator
    mean_gap = sum(gaps) / len(gaps)
    if len(gaps) > 1:
        variance = sum((g - mean_gap) ** 2 for g in gaps) / len(gaps)
        std_gap = variance ** 0.5
    else:
        std_gap = 0
    threshold = mean_gap + 1.5 * std_gap
    # Absolute minimum: never split on gaps < 30pt (within same word group)
    threshold = max(threshold, 30.0)

    groups: list[list] = [[words_sorted_by_x[0]]]
    for i, gap in enumerate(gaps):
        if gap > threshold:
            groups.append([words_sorted_by_x[i + 1]])
        else:
            groups[-1].append(words_sorted_by_x[i + 1])
    return groups


def detect_columns(pdf_path: str, page_idx: int = 1) -> list:
    """
    Scan the header row of a PDF page to detect sub-model column names and
    their x-positions. Uses a gap histogram to find natural break points
    between columns — works even when inter-column gap is only slightly
    larger than intra-column gaps.

    Returns list[ColumnDef] sorted left-to-right with x0/x1 spanning
    between column midpoints for robust pixel scanning.
    """
    MODEL_KEYWORDS = [
        'sport', 'xdrive', 'sdrive', 'edrive', 'coupé', 'coupe',
        'touring', 'gran coupe', 'plug', 'hybrid', 'phev',
        '320', '330', '340', '420', '430', '440', '520', '530', '540',
        '630', '640', '730', '740', '750', '760', 'm2', 'm3', 'm4', 'm5',
        'x1', 'x2', 'x3', 'x4', 'x5', 'x6', 'x7', 'z4', 'ix', 'i5', 'i7',
    ]

    raw_cols: list[ColumnDef] = []

    with pdfplumber.open(pdf_path) as pdf:
        if page_idx >= len(pdf.pages):
            return []
        page = pdf.pages[page_idx]
        words = page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False)

        # Group words right of topic column by y-bucket (4pt buckets)
        rows_by_y: dict[int, list] = {}
        for w in words:
            if float(w['x0']) < TOPIC_MAX_X_PT:
                continue
            y_bucket = int(round(float(w['top']) / 4) * 4)
            rows_by_y.setdefault(y_bucket, []).append(w)

        # Find the header row with highest model-keyword score
        best_row: list = []
        best_score = 0
        for row_words in rows_by_y.values():
            combined = ' '.join(w['text'] for w in row_words).lower()
            score = sum(1 for kw in MODEL_KEYWORDS if kw in combined)
            if score > best_score or (score == best_score and len(row_words) > len(best_row)):
                best_score = score
                best_row = row_words

        if not best_row:
            return []

        best_row.sort(key=lambda w: float(w['x0']))
        groups = _find_column_breaks(best_row)

        for group in groups:
            name = ' '.join(w['text'] for w in group).strip()
            x0 = float(group[0]['x0'])
            x1 = float(group[-1]['x1'])
            cx = (x0 + x1) / 2
            raw_cols.append(ColumnDef(name=name, center_x_pt=cx, x0_pt=x0, x1_pt=x1))

    raw_cols.sort(key=lambda c: c.center_x_pt)
    if not raw_cols:
        return []

    # Expand x0/x1 to span midpoints between adjacent columns
    if len(raw_cols) == 1:
        c = raw_cols[0]
        c.x0_pt = c.center_x_pt - 40
        c.x1_pt = c.center_x_pt + 40
        return raw_cols

    midpoints = [
        (raw_cols[i].center_x_pt + raw_cols[i + 1].center_x_pt) / 2
        for i in range(len(raw_cols) - 1)
    ]
    for i, col in enumerate(raw_cols):
        col.x0_pt = midpoints[i - 1] if i > 0 else col.center_x_pt - 42
        col.x1_pt = midpoints[i]     if i < len(midpoints) else col.center_x_pt + 42

    return raw_cols


# ─── Step 2: Extract topic row y-positions ────────────────────────────────────
def extract_topic_rows(pdf_path: str, page_idx: int, page_height_pt: float) -> list:
    """
    Extract all topic (row label) text from the left column of a page,
    along with their top y-position in PDF points.

    Multi-line continuation detection:
    A new text line is merged into the PREVIOUS row only when ALL of:
      - vertical gap < CONTINUATION_MAX_GAP (10pt)
      - x0 indent >= INDENT_CONTINUATION_X (meaning it's a sub/continuation)
      OR the line starts with '(' indicating English parenthetical of a Thai topic
    Otherwise it starts a new row.
    """
    CONTINUATION_MAX_GAP = 10   # pt — very tight: only merge truly adjacent lines
    TOPIC_X0_MIN = 50           # baseline left margin of topics
    INDENT_CONTINUATION_X = 60  # if x0 > this AND gap < max, treat as continuation

    rows: list[RowData] = []

    with pdfplumber.open(pdf_path) as pdf:
        if page_idx >= len(pdf.pages):
            return []
        page = pdf.pages[page_idx]
        words = page.extract_words(x_tolerance=5, y_tolerance=3, keep_blank_chars=False)

        # Collect words in topic column, grouped by y-bucket (3pt)
        topic_words: dict[int, list] = {}
        for w in words:
            if float(w['x0']) >= TOPIC_MAX_X_PT:
                continue
            y_bucket = int(round(float(w['top']) / 3) * 3)
            topic_words.setdefault(y_bucket, []).append(w)

        # Build topic rows, skip header (top 190pt) and footer (bottom 35pt)
        prev_row: Optional[RowData] = None
        prev_y = -999.0
        prev_x0 = TOPIC_X0_MIN

        for y_bucket in sorted(topic_words.keys()):
            if y_bucket < 190 or y_bucket > page_height_pt - 35:
                continue
            word_list = sorted(topic_words[y_bucket], key=lambda w: float(w['x0']))
            text = ' '.join(w['text'] for w in word_list).strip()
            if not text:
                continue
            line_x0 = float(word_list[0]['x0'])
            y_gap = float(y_bucket) - prev_y

            # Detect continuation line:
            # Case 1: very tight gap + starts with '(' = English parenthetical of Thai topic
            # Case 2: very tight gap + indented more than baseline = sub-label
            is_continuation = (
                prev_row is not None
                and y_gap < CONTINUATION_MAX_GAP
                and (text.startswith('(') or line_x0 > prev_x0 + 5)
            )

            if is_continuation:
                prev_row.topic = prev_row.topic + ' ' + text
            else:
                row = RowData(topic=text, y_top_pt=float(y_bucket))
                rows.append(row)
                prev_row = row
            prev_y = float(y_bucket)

    return rows


# ─── Step 3: Detect checkboxes via pixel scan ──────────────────────────────────
def detect_checkboxes_on_page(
    pdf_path: str,
    page_idx: int,
    cols: list,
    topic_rows: list,
    page_width_pt: float,
    page_height_pt: float,
) -> list:
    """
    Render the PDF page to image and scan each (topic_row × column) cell
    for dark pixel density indicating a checkbox (■).
    Updates topic_rows[i].values in place and returns the list.
    """
    doc = pdfium.PdfDocument(pdf_path)
    if page_idx >= len(doc):
        for row in topic_rows:
            for col in cols:
                row.values[col.name] = "-"
        doc.close()
        return topic_rows

    page = doc[page_idx]
    bitmap = page.render(scale=RENDER_SCALE, rotation=0)
    img = bitmap.to_pil().convert("L")   # grayscale
    doc.close()

    img_w, img_h = img.size
    scale_x = img_w / page_width_pt
    scale_y = img_h / page_height_pt

    # Pre-compute pixel bands for each column (narrow band around center)
    col_bands: list[tuple[int, int, str]] = []
    for col in cols:
        cx_px = int(col.center_x_pt * scale_x)
        x0_px = max(0, cx_px - int(COL_SCAN_HALF_PT * scale_x))
        x1_px = min(img_w, cx_px + int(COL_SCAN_HALF_PT * scale_x))
        col_bands.append((x0_px, x1_px, col.name))

    # Scan each row × column cell
    for i, row in enumerate(topic_rows):
        y_top_px = max(0, int(row.y_top_pt * scale_y) - 2)
        if i + 1 < len(topic_rows):
            y_bot_px = min(img_h, int(topic_rows[i + 1].y_top_pt * scale_y) + 2)
        else:
            y_bot_px = min(img_h, y_top_px + int(14 * scale_y))

        for x0_px, x1_px, col_name in col_bands:
            if x0_px >= x1_px or y_top_px >= y_bot_px:
                row.values[col_name] = "-"
                continue

            region = img.crop((x0_px, y_top_px, x1_px, y_bot_px))
            pixels = list(region.getdata())
            if not pixels:
                row.values[col_name] = "-"
                continue

            dark_count = sum(1 for p in pixels if p < DARK_THRESHOLD)
            density = dark_count / len(pixels)
            row.values[col_name] = "■" if density >= DARK_DENSITY_MIN else "-"

    return topic_rows


# ─── Step 4: Build structured text table for AI ───────────────────────────────
def build_structured_table(
    topic_rows: list,
    cols: list,
    page_idx: int,
    total_pages: int,
) -> str:
    """
    Convert extracted topic rows + column values into a clean text table
    that AI can interpret without any spatial reasoning.
    CHECK = checkbox present (■); - = absent.
    """
    if not cols or not topic_rows:
        return ""

    col_names = [c.name for c in cols]
    col_w = max(16, max(len(n) + 2 for n in col_names))

    lines = [
        f"[PAGE {page_idx + 1} of {total_pages}]",
        f"[COLUMNS left→right: {' | '.join(col_names)}]",
        "─" * (46 + col_w * len(col_names)),
        f"{'Topic':<46}" + "".join(f"{cn:^{col_w}}" for cn in col_names),
        "─" * (46 + col_w * len(col_names)),
    ]

    for row in topic_rows:
        topic_cell = row.topic[:45]
        value_cells = "".join(
            f"{'CHECK':^{col_w}}" if row.values.get(cn, "-") == "■"
            else f"{'-':^{col_w}}"
            for cn in col_names
        )
        lines.append(f"{topic_cell:<46}{value_cells}")

    lines.append("─" * (46 + col_w * len(col_names)))
    return "\n".join(lines)


# ─── Public API ───────────────────────────────────────────────────────────────
def extract_page_structured(
    pdf_path: str,
    page_idx: int,
    cols: Optional[list] = None,
) -> tuple:
    """
    Full pipeline for one page:
      PDF page → column detection → topic rows → pixel checkbox scan → structured text
    Returns (structured_text: str, topic_rows: list[RowData]).
    If cols is None, auto-detect from page 0.
    """
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        if page_idx >= total_pages:
            return "", []
        page = pdf.pages[page_idx]
        page_w = float(page.width)
        page_h = float(page.height)

    if cols is None:
        cols = detect_columns(pdf_path, page_idx=0)
    if not cols:
        return "", []

    topic_rows = extract_topic_rows(pdf_path, page_idx, page_h)
    if not topic_rows:
        return "", []

    topic_rows = detect_checkboxes_on_page(
        pdf_path, page_idx, cols, topic_rows, page_w, page_h
    )

    structured_text = build_structured_table(topic_rows, cols, page_idx, total_pages)
    return structured_text, topic_rows


def get_page_count(pdf_path: str) -> int:
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


def quality_check(topic_rows: list) -> bool:
    """
    Returns True if extraction looks usable.
    Used to decide whether to fallback to raw PDF upload mode.
    """
    if not topic_rows or len(topic_rows) < 3:
        return False
    checks = sum(
        1 for row in topic_rows
        if any(v == "■" for v in row.values.values())
    )
    return checks >= 1
