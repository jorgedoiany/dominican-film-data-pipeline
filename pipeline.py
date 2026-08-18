import json
import os
import sys

from database.db_setup import get_connection, fix_tax_credit_pct
from extractor.pdf_extractor import (
    insert_cipac_resolution,
    print_review_summary,
    process_all_pdfs,
)


def run_pipeline(years: list[str] | None = None, force_ocr: bool = False, skip_existing: bool = False) -> None:
    """
    Run full CIPAC extraction pipeline:
    1. Load from JSON if exists, otherwise process PDFs with OCR
    2. Print quality summary
    3. Insert into SQLite database
    4. Fix tax_credit_pct based on incentive_article

    Args:
        years:         List of years to process. None processes all years.
        force_ocr:     If True, re-run OCR even if JSON results already exist.
        skip_existing: If True, skip PDFs already in the JSON.
    """
    print("Starting CIPAC extraction pipeline...")
    print("─" * 50)

    year_label = '_'.join(years) if years else 'all'
    json_path = os.path.join('data', f'cipac_{year_label}_results.json')

    # ── Step 1: Load from JSON or process PDFs ──
    if os.path.exists(json_path) and not force_ocr and not skip_existing:
        print(f"\nLoading existing results from: {json_path}")
        with open(json_path, encoding='utf-8') as f:
            results = json.load(f)
        print(f"Loaded {len(results)} results from JSON.")
    else:
        results = process_all_pdfs(year_filter=years, skip_existing=skip_existing)
        if not results:
            print("No results found.")
            return
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nResults saved to: {json_path}")

    # ── Step 2: Quality summary ──
    print_review_summary(results)

    # ── Step 3: Insert into database ──
    print("\nInserting into database...")
    conn = get_connection()
    inserted = 0
    skipped = 0

    for r in results:
        if insert_cipac_resolution(conn, r):
            inserted += 1
        else:
            skipped += 1

    print(f"  Inserted: {inserted}")
    print(f"  Skipped:  {skipped}")

    # ── Step 4: Fix tax_credit_pct ──
    fix_tax_credit_pct(conn, results)

    conn.close()
    print("\nPipeline complete.")


if __name__ == "__main__":
    force_ocr = '--force-ocr' in sys.argv
    years = [y for y in sys.argv[1:] if y != '--force-ocr'] or None
    run_pipeline(years=years, force_ocr=force_ocr)