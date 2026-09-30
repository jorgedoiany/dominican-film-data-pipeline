import sqlite3
import os
import pandas as pd


# ─────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(BASE_DIR, 'schema.sql')
DB_PATH = os.path.join(BASE_DIR, 'dgcine.db')


def create_database(db_path: str = DB_PATH) -> None:
    """Create the SQLite database from schema.sql."""
    print("Creating database...")

    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        schema = f.read()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.executescript(schema)
    conn.commit()
    conn.close()

    print(f"Database created at: {db_path}")


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Return a connection to the database."""
    if not os.path.exists(db_path):
        create_database(db_path)
    return sqlite3.connect(db_path)


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


PRODUCTION_COLUMNS = [
    'project_id', 'film_title', 'commercial_title', 'pur_number', 'cpnd_number',
    'production_year', 'release_date', 'type', 'genre', 'duration_min',
    'country_of_origin', 'coproduction_country', 'production_origin', 'status',
    'director', 'screenplay_author', 'production_company', 'short_synopsis',
    'synopsis_source', 'total_budget_approved', 'original_language',
]
PRODUCTION_INT_COLUMNS = {'pur_number', 'cpnd_number', 'production_year', 'duration_min'}
PRODUCTION_FLOAT_COLUMNS = {'total_budget_approved'}


def load_productions(csv_path: str, db_path: str = DB_PATH) -> None:
    """Load productions from 01_movies.csv (upsert by project_id)."""
    print(f"Loading productions from {csv_path}...")

    df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')

    missing = set(PRODUCTION_COLUMNS) - set(df.columns)
    extra = set(df.columns) - set(PRODUCTION_COLUMNS)
    if missing or extra:
        raise ValueError(f"Unexpected CSV columns. Missing: {sorted(missing)}. Extra: {sorted(extra)}.")
    if df['project_id'].isna().any() or df['project_id'].duplicated().any():
        raise ValueError("project_id must be present and unique in every row.")
    if df['film_title'].isna().any():
        raise ValueError("film_title must be present in every row.")

    def clean(value, column):
        if pd.isna(value):
            return None
        if column in PRODUCTION_INT_COLUMNS:
            return int(value)
        if column in PRODUCTION_FLOAT_COLUMNS:
            return float(value)
        return value

    rows = [
        tuple(clean(row[col], col) for col in PRODUCTION_COLUMNS)
        for _, row in df[PRODUCTION_COLUMNS].iterrows()
    ]

    placeholders = ','.join('?' * len(PRODUCTION_COLUMNS))
    conn = get_connection(db_path)
    conn.executemany(
        f"INSERT OR REPLACE INTO productions ({', '.join(PRODUCTION_COLUMNS)}) VALUES ({placeholders})",
        rows,
    )
    conn.commit()
    conn.close()

    print(f"Loaded {len(rows)} productions into database.")


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