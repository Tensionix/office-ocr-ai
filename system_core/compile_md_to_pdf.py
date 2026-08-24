from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from project_paths import ensure_project_dirs, iter_project_files, normalized_source_relative_path, output_path_for

from compile_md_to_docx import compile_markdown_to_docx_single


def convert_to_pdf_via_word(docx_path: Path, pdf_path: Path) -> bool:
    try:
        import win32com.client
    except Exception as exc:
        print(f"[ERROR] pywin32 / win32com is unavailable: {exc}")
        return False

    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(docx_path.resolve()))
        doc.SaveAs(str(pdf_path.resolve()), FileFormat=17)
        doc.Close(False)
        return True
    except Exception as exc:
        print(f"   [FAIL] PDF export error: {exc}")
        return False
    finally:
        if word is not None:
            word.Quit()


def build_pdf_pipeline() -> None:
    ensure_project_dirs()
    md_files = iter_project_files({".md"})
    if not md_files:
        print("[INFO] No .md files found in project root.")
        return

    print("=== AUDION OFFICE OCR AI: PDF COMPILER ===")
    print("Engine: Microsoft Word COM\n")

    for md_file in md_files:
        rel_path = normalized_source_relative_path(md_file)
        temp_docx = output_path_for(md_file, ".pdf.temp.docx")
        final_pdf = output_path_for(md_file, ".pdf")
        final_pdf.parent.mkdir(parents=True, exist_ok=True)

        print(f"[BUILD] {rel_path} -> PDF")
        compile_markdown_to_docx_single(md_file, temp_docx)
        success = convert_to_pdf_via_word(temp_docx, final_pdf)
        if temp_docx.exists():
            temp_docx.unlink()
        print("   [OK] Done." if success else "   [FAIL] Conversion failed.")


if __name__ == "__main__":
    os.system("cls" if os.name == "nt" else "clear")
    build_pdf_pipeline()
