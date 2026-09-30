"""
Migration 001: movie_id -> project_id (schema v2.0), SQLite.

What it does on the database given with --db:
  1. Aborts if the database is already v2.0 or if the certificate tables are not empty.
  2. Replaces `productions` and the empty certificate tables with the v2.0 schema and
     recreates `cipac_resolutions`, copying every row (manual review fields included).
     The copy is verified before the old table is dropped.
  3. Loads 01_movies.csv into `productions`.
  4. Fills cipac_resolutions.project_id by matching pur_number against productions.
     Resolutions whose PUR has no production keep project_id NULL.

Always run it on a copy first. If a step fails, restore from a backup and run again.
"""
import argparse
import os
import sqlite3
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from database.db_setup import SCHEMA_PATH, load_productions  # noqa: E402

CERT_TABLES = ['cpnd_certificates', 'pur_certificates', 'validation_files']


def columns(conn, table):
    return [row[1] for row in conn.execute(f'PRAGMA table_info({table})')]


def count(conn, sql):
    return conn.execute(sql).fetchone()[0]


def run_schema(conn):
    """Run schema.sql statement by statement so the open transaction is kept."""
    buffer = ''
    with open(SCHEMA_PATH, encoding='utf-8') as f:
        for line in f:
            buffer += line
            if sqlite3.complete_statement(buffer):
                conn.execute(buffer)
                buffer = ''


def phase_a(conn):
    old_cols = columns(conn, 'cipac_resolutions')
    if 'project_id' in old_cols or 'project_id' in columns(conn, 'productions'):
        sys.exit('Already migrated (project_id found). Nothing to do.')
    if 'movie_id' not in old_cols:
        sys.exit('Unexpected schema: cipac_resolutions has no movie_id.')
    for table in CERT_TABLES:
        n = count(conn, f'SELECT COUNT(*) FROM {table}')
        if n:
            sys.exit(f'{table} has {n} rows; this migration expects it to be empty.')

    copy_cols = [c for c in old_cols if c != 'movie_id']
    col_list = ', '.join(copy_cols)
    total_before = count(conn, 'SELECT COUNT(*) FROM cipac_resolutions')
    manual_before = count(conn, 'SELECT COUNT(*) FROM cipac_resolutions WHERE manually_reviewed = 1')

    conn.execute('BEGIN')
    try:
        index_names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL").fetchall()]
        for name in index_names:
            conn.execute(f'DROP INDEX {name}')
        conn.execute('ALTER TABLE cipac_resolutions RENAME TO cipac_resolutions_old')
        for table in CERT_TABLES + ['productions']:
            conn.execute(f'DROP TABLE {table}')
        run_schema(conn)

        new_cols = columns(conn, 'cipac_resolutions')
        if set(new_cols) - {'project_id'} != set(copy_cols):
            raise RuntimeError('Column mismatch between old and new cipac_resolutions.')
        conn.execute(
            f'INSERT INTO cipac_resolutions ({col_list}) '
            f'SELECT {col_list} FROM cipac_resolutions_old')

        total_after = count(conn, 'SELECT COUNT(*) FROM cipac_resolutions')
        manual_after = count(conn, 'SELECT COUNT(*) FROM cipac_resolutions WHERE manually_reviewed = 1')
        missing = count(conn, f'SELECT COUNT(*) FROM (SELECT {col_list} FROM cipac_resolutions_old '
                              f'EXCEPT SELECT {col_list} FROM cipac_resolutions)')
        extra = count(conn, f'SELECT COUNT(*) FROM (SELECT {col_list} FROM cipac_resolutions '
                            f'EXCEPT SELECT {col_list} FROM cipac_resolutions_old)')
        if (total_after, manual_after, missing, extra) != (total_before, manual_before, 0, 0):
            raise RuntimeError(
                f'Verification failed: rows {total_before}->{total_after}, '
                f'manual {manual_before}->{manual_after}, missing={missing}, extra={extra}.')
        conn.execute('DROP TABLE cipac_resolutions_old')
        conn.execute('COMMIT')
    except Exception:
        conn.execute('ROLLBACK')
        raise
    print(f'Phase A OK: {total_after} resolutions copied, {manual_after} manually reviewed preserved.')


def phase_c(conn):
    conn.execute('BEGIN')
    try:
        conn.execute("""
            UPDATE cipac_resolutions
            SET project_id = (
                SELECT p.project_id FROM productions p
                WHERE p.pur_number = CAST(cipac_resolutions.pur_number AS INTEGER)
            )
            WHERE pur_number GLOB '[0-9]*'
        """)
        conn.execute('COMMIT')
    except Exception:
        conn.execute('ROLLBACK')
        raise


def report(conn):
    print('--- Result ---')
    print('productions:', count(conn, 'SELECT COUNT(*) FROM productions'))
    print('cipac_resolutions:', count(conn, 'SELECT COUNT(*) FROM cipac_resolutions'),
          '| with project_id:', count(conn, 'SELECT COUNT(project_id) FROM cipac_resolutions'),
          '| manually_reviewed:', count(conn, 'SELECT COUNT(*) FROM cipac_resolutions WHERE manually_reviewed = 1'))
    print('Resolutions without project_id:')
    for row in conn.execute("SELECT resolution_number, pur_number, film_title "
                            "FROM cipac_resolutions WHERE project_id IS NULL ORDER BY resolution_number"):
        print('  ', row)


def main():
    parser = argparse.ArgumentParser(description='Migrate a SQLite database from schema v1.0 to v2.0.')
    parser.add_argument('--db', required=True, help='Path to the SQLite database to migrate.')
    parser.add_argument('--csv', required=True, help='Path to the new 01_movies.csv.')
    args = parser.parse_args()
    for path in (args.db, args.csv):
        if not os.path.exists(path):
            sys.exit(f'File not found: {path}')

    conn = sqlite3.connect(args.db, isolation_level=None)
    phase_a(conn)
    load_productions(args.csv, args.db)
    phase_c(conn)
    report(conn)
    conn.close()


if __name__ == '__main__':
    main()
