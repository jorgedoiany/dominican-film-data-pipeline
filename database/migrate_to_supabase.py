import os
import sqlite3
import psycopg2
from dotenv import load_dotenv

load_dotenv()

SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dgcine.db')


def get_sqlite_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_postgres_connection():
    return psycopg2.connect(os.getenv('SUPABASE_DB_URL'))


def migrate_productions(sqlite_conn, pg_conn) -> int:
    """Migrate productions table."""
    cursor_sqlite = sqlite_conn.cursor()
    cursor_pg = pg_conn.cursor()

    cursor_sqlite.execute('SELECT * FROM productions')
    rows = cursor_sqlite.fetchall()

    inserted = 0
    for row in rows:
        cursor_pg.execute("""
            INSERT INTO productions (
                movie_id, title, production_year, release_year, genre,
                duration_min, coproduction_country, status, director,
                screenplay_author, production_company, short_synopsis,
                synopsis_source, approx_budget, original_language,
                production_type, incentive_type
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (movie_id) DO NOTHING
        """, tuple(row))
        inserted += 1

    pg_conn.commit()
    return inserted


def migrate_cipac_resolutions(sqlite_conn, pg_conn) -> int:
    """Migrate cipac_resolutions table."""
    cursor_sqlite = sqlite_conn.cursor()
    cursor_pg = pg_conn.cursor()

    cursor_sqlite.execute('SELECT * FROM cipac_resolutions')
    rows = cursor_sqlite.fetchall()

    inserted = 0
    for row in rows:
        cursor_pg.execute("""
            INSERT INTO cipac_resolutions (
                resolution_number, year, file_id, movie_id, pur_number,
                cpnd_number, incentive_article, resolution_type,
                investor_name, investor_rnc, local_company, producer_rnc,
                foreign_producer, film_title, request_date, resolution_date,
                validated_expenses_dop, tax_credit_dop, tax_credit_pct,
                total_budget_approved, total_budget_executed,
                extraction_confidence, needs_review, review_reasons,
                manually_reviewed, manual_note, source_file
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )
            ON CONFLICT (resolution_number) DO UPDATE SET
                investor_name = EXCLUDED.investor_name,
                investor_rnc = EXCLUDED.investor_rnc,
                local_company = EXCLUDED.local_company,
                producer_rnc = EXCLUDED.producer_rnc,
                film_title = EXCLUDED.film_title,
                validated_expenses_dop = EXCLUDED.validated_expenses_dop,
                tax_credit_dop = EXCLUDED.tax_credit_dop,
                total_budget_approved = EXCLUDED.total_budget_approved,
                total_budget_executed = EXCLUDED.total_budget_executed,
                manually_reviewed = EXCLUDED.manually_reviewed,
                manual_note = EXCLUDED.manual_note
        """, tuple(row)[1:])
        inserted += 1

    pg_conn.commit()
    return inserted


def main():
    print("Starting migration to Supabase...")
    print("─" * 50)

    sqlite_conn = get_sqlite_connection()
    pg_conn = get_postgres_connection()

    print("Migrating productions...")
    n = migrate_productions(sqlite_conn, pg_conn)
    print(f"  Inserted: {n}")

    print("Migrating cipac_resolutions...")
    n = migrate_cipac_resolutions(sqlite_conn, pg_conn)
    print(f"  Inserted: {n}")

    sqlite_conn.close()
    pg_conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    main()