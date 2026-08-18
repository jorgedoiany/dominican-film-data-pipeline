import sys
from scraper.cipac_scraper import scrape_resolutions
from pipeline import run_pipeline
from database.migrate_to_supabase import main as migrate_to_supabase


def update(year: str):
    print(f"Updating {year}...")
    print("─" * 50)

    print("\n1. Scraping new PDFs...")
    scrape_resolutions(download=True)

    print("\n2. Processing new PDFs...")
    run_pipeline(years=[year], force_ocr=False, skip_existing=True)

    print("\n3. Manual review required.")
    print(f"   Check data/cipac_{year}_results.json for records with needs_review=true.")
    print("   Make any manual corrections before continuing.")
    input("\n   Press ENTER when ready to migrate to Supabase...")

    print("\n4. Migrating to Supabase...")
    migrate_to_supabase()

    print(f"\nDone! {year} updated successfully.")


if __name__ == "__main__":
    year = sys.argv[1] if len(sys.argv) > 1 else None
    if not year:
        print("Usage: python update.py 2026")
        sys.exit(1)
    update(year)