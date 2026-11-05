"""Reads the live PostgreSQL schema and renders a compact, LLM-friendly description
(columns, PK/FK, column comments, and the actual values of low-cardinality text columns)."""
import psycopg
from psycopg import sql

from .config import Settings

COLS_SQL = """
SELECT c.table_name, c.column_name, c.data_type, pgd.description
FROM information_schema.columns c
LEFT JOIN pg_catalog.pg_statio_all_tables st ON st.schemaname = c.table_schema AND st.relname = c.table_name
LEFT JOIN pg_catalog.pg_description pgd ON pgd.objoid = st.relid AND pgd.objsubid = c.ordinal_position
WHERE c.table_schema = 'public'
ORDER BY c.table_name, c.ordinal_position
"""

CONSTRAINT_SQL = """
SELECT tc.table_name, kcu.column_name, tc.constraint_type, ccu.table_name, ccu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu
  ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
WHERE tc.table_schema = 'public' AND tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY')
"""


class SchemaProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._context: str | None = None
        self._tables: set[str] = set()

    @property
    def tables(self) -> set[str]:
        self.get_context()
        return self._tables

    def get_context(self) -> str:
        if self._context is None:
            self._context = self._load()
        return self._context

    def refresh(self) -> None:
        self._context = None

    def _load(self) -> str:
        with psycopg.connect(self.settings.database_url) as conn, conn.cursor() as cur:
            cur.execute(COLS_SQL)
            cols = cur.fetchall()
            cur.execute(CONSTRAINT_SQL)
            constraints = cur.fetchall()
            samples: dict[tuple[str, str], list[str]] = {}
            for table, col, dtype, _ in cols:
                if dtype in ("text", "character varying"):
                    cur.execute(sql.SQL("SELECT DISTINCT {c} FROM {t} WHERE {c} IS NOT NULL LIMIT 11")
                                .format(c=sql.Identifier(col), t=sql.Identifier(table)))
                    vals = sorted(r[0] for r in cur.fetchall())
                    if len(vals) <= 10:
                        samples[(table, col)] = vals

        pk = {(t, c) for t, c, kind, *_ in constraints if kind == "PRIMARY KEY"}
        fk = {(t, c): f"{ft}.{fc}" for t, c, kind, ft, fc in constraints if kind == "FOREIGN KEY"}

        lines: list[str] = []
        current = None
        for table, col, dtype, comment in cols:
            if table != current:
                lines.append(f"\nTABLE {table}")
                current = table
                self._tables.add(table)
            extras = []
            if (table, col) in pk:
                extras.append("PRIMARY KEY")
            if (table, col) in fk:
                extras.append(f"FOREIGN KEY -> {fk[(table, col)]}")
            if comment:
                extras.append(f"note: {comment}")
            if (table, col) in samples:
                extras.append("values: " + ", ".join(f"'{v}'" for v in samples[(table, col)]))
            lines.append(f"  - {col} {dtype}" + (f"  [{'; '.join(extras)}]" if extras else ""))
        return "\n".join(lines).strip()
