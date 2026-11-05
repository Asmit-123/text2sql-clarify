import psycopg

from .config import Settings


def execute_query(settings: Settings, sql: str, row_limit: int | None = None):
    """Run SQL in a READ ONLY transaction with a statement timeout. Returns (columns, rows)."""
    with psycopg.connect(settings.database_url) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL statement_timeout = {int(settings.statement_timeout_ms)}")
            cur.execute(sql)
            columns = [d.name for d in cur.description]
            rows = cur.fetchmany(row_limit or settings.row_limit)
    return columns, rows
