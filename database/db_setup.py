import sqlite3
import os
import pandas as pd


# ─────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(BASE_DIR, 'schema.sql')
DB_PATH = os.path.join(BASE_DIR, 'dgcine.db')


def create_database() -> None:
    """Create the SQLite database from schema.sql."""
    print("Creating database...")

    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        schema = f.read()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executescript(schema)
    conn.commit()
    conn.close()

    print(f"Database created at: {DB_PATH}")


def get_connection() -> sqlite3.Connection:
    """Return a connection to the database."""
    if not os.path.exists(DB_PATH):
        create_database()
    return sqlite3.connect(DB_PATH)


def get_table_info() -> None:
    """Print table names and row counts."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()

    print("\nDatabase tables:")
    print("─" * 40)
    for (table,) in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"  {table:<25} {count:>6} rows")

    conn.close()


def load_productions(csv_path: str) -> None:
    """Load productions from 01_movies.csv into the database."""
    print(f"Loading productions from {csv_path}...")

    df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')

    df = df.rename(columns={
        'movie_id':             'movie_id',
        'title':                'title',
        'production_year':      'production_year',
        'release_year':         'release_year',
        'genre':                'genre',
        'duration_min':         'duration_min',
        'coproduction_country': 'coproduction_country',
        'status':               'status',
        'director':             'director',
        'screenplay_author':    'screenplay_author',
        'production_company':   'production_company',
        'short_synopsis':       'short_synopsis',
        'synopsis_source':      'synopsis_source',
        'approx_budget':        'approx_budget',
        'original_language':    'original_language',
    })

    df['production_type'] = 'dominican'
    df['incentive_type'] = 'unknown'

    db_columns = [
        'movie_id', 'title', 'production_year', 'release_year',
        'genre', 'duration_min', 'coproduction_country', 'status',
        'director', 'screenplay_author', 'production_company',
        'short_synopsis', 'synopsis_source', 'approx_budget',
        'original_language', 'production_type', 'incentive_type'
    ]

    df = df[[col for col in db_columns if col in df.columns]]

    conn = get_connection()
    df.to_sql('productions', conn, if_exists='replace', index=False)
    conn.commit()
    conn.close()

    print(f"Loaded {len(df)} productions into database.")


def fix_tax_credit_pct(conn: sqlite3.Connection, results: list[dict]) -> None:
    """
    Fix tax_credit_pct based on incentive_article extracted from PDF text:
    - Art. 34 (Dominican): 100% of investment is deductible
    - Art. 39 (Foreign):   25% transferable tax credit on DR expenses
    - Unknown:             NULL
    """
    cursor = conn.cursor()
    updated_34 = 0
    updated_39 = 0
    unknown = 0

    for r in results:
        resolution = r.get('resolution_number')
        incentive = r.get('incentive_article')

        if incentive == 'art_34':
            pct = 100.0
            updated_34 += 1
        elif incentive == 'art_39':
            pct = 25.0
            updated_39 += 1
        else:
            pct = None
            unknown += 1

        cursor.execute(
            'UPDATE cipac_resolutions SET tax_credit_pct = ? WHERE resolution_number = ?',
            (pct, resolution)
        )

    conn.commit()

    print("\ntax_credit_pct updated:")
    print(f"  Art. 34 (100%):  {updated_34} resolutions")
    print(f"  Art. 39 (25%):   {updated_39} resolutions")
    print(f"  Unknown (NULL):  {unknown} resolutions")


if __name__ == "__main__":
    create_database()
    load_productions('../dominican-film-dashboard/data/01_movies.csv')
    get_table_info()