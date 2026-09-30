import argparse
import os
import sqlite3
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dgcine.db')


SCHEMA_PG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema_postgres.sql')
DROP_ORDER = ['cipac_resolutions', 'validation_files', 'pur_certificates',
              'cpnd_certificates', 'productions']
PRODUCTION_COLUMNS = [
    'project_id', 'film_title', 'commercial_title', 'pur_number', 'cpnd_number',
    'production_year', 'release_date', 'type', 'genre', 'duration_min',
    'country_of_origin', 'coproduction_country', 'production_origin', 'status',
    'director', 'screenplay_author', 'production_company', 'short_synopsis',
    'synopsis_source', 'total_budget_approved', 'original_language',
]


def get_sqlite_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_postgres_connection():
    return psycopg2.connect(os.getenv('SUPABASE_DB_URL'))


def recreate_schema(pg_conn) -> None:
    """DROP and recreate all tables from schema_postgres.sql (destructive)."""
    cursor = pg_conn.cursor()
    for table in DROP_ORDER:
        cursor.execute(f'DROP TABLE IF EXISTS {table}')
    with open(SCHEMA_PG_PATH, encoding='utf-8') as f:
        cursor.execute(f.read())


def migrate_productions(sqlite_conn, pg_conn) -> int:
    """Migrate productions table (upsert by project_id). Caller commits."""
    cursor_pg = pg_conn.cursor()
    cols = ', '.join(PRODUCTION_COLUMNS)
    rows = sqlite_conn.execute(f'SELECT {cols} FROM productions').fetchall()
    placeholders = ','.join(['%s'] * len(PRODUCTION_COLUMNS))
    updates = ', '.join(f'{c} = EXCLUDED.{c}' for c in PRODUCTION_COLUMNS if c != 'project_id')
    for row in rows:
        cursor_pg.execute(f"""
            INSERT INTO productions ({cols}) VALUES ({placeholders})
            ON CONFLICT (project_id) DO UPDATE SET {updates}
        """, tuple(row))
    return len(rows)


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
                resolution_number, year, file_id, project_id, pur_number,
                cpnd_number, incentive_article, resolution_type,
                investor_name, investor_rnc, production_company, producer_rnc,
                foreign_producer, film_title, request_date, resolution_date,
                validated_amount_dop, tax_credit_dop, tax_credit_pct,
                total_budget_approved, total_budget_executed,
                extraction_confidence, needs_review, review_reasons,
                manually_reviewed, manual_note, source_file
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )
            ON CONFLICT (resolution_number) DO UPDATE SET
                year = EXCLUDED.year,
                file_id = EXCLUDED.file_id,
                project_id = EXCLUDED.project_id,
                pur_number = EXCLUDED.pur_number,
                cpnd_number = EXCLUDED.cpnd_number,
                incentive_article = EXCLUDED.incentive_article,
                resolution_type = EXCLUDED.resolution_type,
                investor_name = EXCLUDED.investor_name,
                investor_rnc = EXCLUDED.investor_rnc,
                production_company = EXCLUDED.production_company,
                producer_rnc = EXCLUDED.producer_rnc,
                foreign_producer = EXCLUDED.foreign_producer,
                film_title = EXCLUDED.film_title,
                request_date = EXCLUDED.request_date,
                resolution_date = EXCLUDED.resolution_date,
                validated_amount_dop = EXCLUDED.validated_amount_dop,
                tax_credit_dop = EXCLUDED.tax_credit_dop,
                tax_credit_pct = EXCLUDED.tax_credit_pct,
                total_budget_approved = EXCLUDED.total_budget_approved,
                total_budget_executed = EXCLUDED.total_budget_executed,
                extraction_confidence = EXCLUDED.extraction_confidence,
                needs_review = EXCLUDED.needs_review,
                review_reasons = EXCLUDED.review_reasons,
                manually_reviewed = EXCLUDED.manually_reviewed,
                manual_note = EXCLUDED.manual_note,
                source_file = EXCLUDED.source_file
        """, tuple(row)[1:])
        inserted += 1

    return inserted


def report(pg_conn) -> None:
    cursor = pg_conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM productions')
    print('  productions:', cursor.fetchone()[0])
    cursor.execute('SELECT COUNT(*), COUNT(project_id), '
                   'COUNT(*) FILTER (WHERE manually_reviewed = 1) FROM cipac_resolutions')
    total, with_pid, manual = cursor.fetchone()
    print(f'  cipac_resolutions: {total} | with project_id: {with_pid} | manually_reviewed: {manual}')


def main():
    parser = argparse.ArgumentParser(description='Migrate dgcine.db (SQLite, schema v2.0) to Supabase.')
    parser.add_argument('--recreate-schema', action='store_true',
                        help='DROP and recreate all tables from schema_postgres.sql (destructive).')
    parser.add_argument('--dry-run', action='store_true',
                        help='Run everything inside the transaction, print counts, then ROLLBACK.')
    args = parser.parse_args()

    sqlite_conn = get_sqlite_connection()
    columns = [row[1] for row in sqlite_conn.execute('PRAGMA table_info(productions)')]
    if 'project_id' not in columns:
        sys.exit('SQLite is not on schema v2.0 (productions.project_id not found). Migrate it first.')

    if args.recreate_schema and not args.dry_run:
        print('This will DROP and recreate all tables in Supabase.')
        if input('Type RECREATE to continue: ') != 'RECREATE':
            sys.exit('Aborted.')

    print('Starting migration to Supabase...')
    print('─' * 50)
    pg_conn = get_postgres_connection()
    try:
        if args.recreate_schema:
            recreate_schema(pg_conn)
            print('Schema recreated (inside the transaction).')

        print('Migrating productions...')
        print(f'  Processed: {migrate_productions(sqlite_conn, pg_conn)}')

        print('Migrating cipac_resolutions...')
        print(f'  Processed: {migrate_cipac_resolutions(sqlite_conn, pg_conn)}')

        print('Verification (inside the transaction):')
        report(pg_conn)

        if args.dry_run:
            pg_conn.rollback()
            print('\nDry run: rolled back, nothing was saved.')
        else:
            pg_conn.commit()
            print('\nMigration complete.')
    except Exception:
        pg_conn.rollback()
        raise
    finally:
        sqlite_conn.close()
        pg_conn.close()


if __name__ == "__main__":
    main()
