"""
page_splitter.py
----------------
Utility module for splitting BMW brochure PDFs into individual single-page PDFs.
Used by batch_extractor.py to enable page-by-page Gemini API calls, preventing
ReadTimeout/504/503 errors caused by large multi-page PDF contexts.

Dependency: pypdf  (pip install pypdf)
"""

import os
import glob

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    raise ImportError(
        "[page_splitter] 'pypdf' is not installed. "
        "Please run:  pip install pypdf"
    )


def get_page_count(pdf_path: str) -> int:
    """
    Return the total number of pages in the given PDF file.

    Args:
        pdf_path: Absolute or relative path to the PDF file.

    Returns:
        Integer page count.
    """
    reader = PdfReader(pdf_path)
    return len(reader.pages)


def extract_single_page(pdf_path: str, page_index: int, out_dir: str) -> str:
    """
    Extract a single page from a PDF and write it as a standalone single-page PDF.

    The output filename is:
        <original_basename_without_ext>_p<page_number>.pdf
    where page_number = page_index + 1  (1-based, for human-readable filenames).

    Args:
        pdf_path:    Path to the source PDF file.
        page_index:  Zero-based index of the page to extract.
        out_dir:     Directory where the single-page PDF will be written.
                     Created automatically if it does not exist.

    Returns:
        Absolute path of the written single-page PDF file.

    Raises:
        IndexError:  If page_index is out of range for the given PDF.
        FileNotFoundError: If pdf_path does not exist.
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"[page_splitter] Source PDF not found: {pdf_path}")

    os.makedirs(out_dir, exist_ok=True)

    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)

    if page_index < 0 or page_index >= total_pages:
        raise IndexError(
            f"[page_splitter] page_index={page_index} is out of range "
            f"for PDF with {total_pages} pages: {pdf_path}"
        )

    basename = os.path.splitext(os.path.basename(pdf_path))[0]
    out_filename = f"{basename}_p{page_index + 1}.pdf"
    out_path = os.path.join(out_dir, out_filename)

    writer = PdfWriter()
    writer.add_page(reader.pages[page_index])

    with open(out_path, "wb") as f:
        writer.write(f)

    return os.path.abspath(out_path)


def split_all_pages(pdf_path: str, out_dir: str) -> list:
    """
    Split every page of a PDF into individual single-page PDFs in out_dir.

    Args:
        pdf_path: Path to the source PDF file.
        out_dir:  Output directory for single-page PDFs.

    Returns:
        Ordered list of absolute paths to the written single-page PDF files
        (index 0 = page 1 of source, etc.).
    """
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    out_paths = []

    for page_index in range(total_pages):
        out_path = extract_single_page(pdf_path, page_index, out_dir)
        out_paths.append(out_path)

    return out_paths


def cleanup_temp_pages(out_dir: str) -> None:
    """
    Remove all *.pdf files inside out_dir that were created by this module.
    The directory itself is left in place (it may contain other files).

    Args:
        out_dir: Path to the temporary pages directory to clean.
    """
    if not os.path.isdir(out_dir):
        return

    pattern = os.path.join(out_dir, "*.pdf")
    files = glob.glob(pattern)
    removed = 0
    for f in files:
        try:
            os.remove(f)
            removed += 1
        except OSError as e:
            print(f"   [page_splitter WARNING] Could not remove temp file {f}: {e}")

    if removed:
        print(f"   [page_splitter] Cleaned up {removed} temp page file(s) from '{out_dir}'.")
