"""Guardrails between the LLM and the database: AST-level read-only + known-tables check."""
import sqlglot
from sqlglot import exp


class UnsafeSQLError(ValueError):
    pass


_FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command, exp.Merge)


def validate_sql(sql: str, allowed_tables: set[str]) -> None:
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as exc:
        raise UnsafeSQLError(f"SQL does not parse: {exc}") from exc
    if len(statements) != 1 or statements[0] is None:
        raise UnsafeSQLError("exactly one statement is allowed")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union)):
        raise UnsafeSQLError("only SELECT statements are allowed")
    if any(tree.find_all(*_FORBIDDEN)):
        raise UnsafeSQLError("statement contains a write/DDL operation")
    ctes = {c.alias for c in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if table.name not in allowed_tables and table.name not in ctes:
            raise UnsafeSQLError(f"unknown table '{table.name}'")
