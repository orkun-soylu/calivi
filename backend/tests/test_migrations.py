"""Schema migrations on an ALREADY DEPLOYED database.

This file exists because of a production outage. `disabled_tools` was added to the `McpServer`
model with no matching `ALTER TABLE` in `_migrate()`. Every test passed — the test database is
built from the models on each run, so the column was always there — and the deployed instance,
whose `mcp_servers` table predated the column, went to **502** on the first query:
`no such column: mcp_servers.disabled_tools`.

`Base.metadata.create_all()` creates missing **tables**. It never adds missing **columns**. Any
column added to a table that already exists somewhere needs an explicit `ALTER TABLE` here, and
a test that runs against the *old* shape rather than the freshly generated one.
"""
from app import models
from app.database import SessionLocal, _migrate, engine

# The mcp_servers table exactly as it shipped before disabled_tools existed.
LEGACY_MCP_SERVERS = """
CREATE TABLE mcp_servers (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    url VARCHAR(500) NOT NULL,
    transport VARCHAR(10) NOT NULL,
    secret VARCHAR(1000),
    secret_header VARCHAR(100) NOT NULL,
    secret_prefix VARCHAR(20) NOT NULL,
    headers JSON,
    enabled BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    UNIQUE (name)
)
"""


def _rebuild_legacy_table():
    with engine.connect() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS mcp_servers")
        conn.exec_driver_sql(LEGACY_MCP_SERVERS)
        conn.commit()


def _columns(table):
    with engine.connect() as conn:
        return [row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()]


def test_migrate_adds_disabled_tools_to_a_pre_existing_table():
    _rebuild_legacy_table()
    assert "disabled_tools" not in _columns("mcp_servers")  # the deployed shape

    _migrate()

    assert "disabled_tools" in _columns("mcp_servers")


def test_the_query_that_took_production_down_works_after_migrating():
    """`sync_all()` issues exactly this query on startup — it is what returned 502."""
    _rebuild_legacy_table()
    _migrate()

    db = SessionLocal()
    try:
        assert db.query(models.McpServer).all() == []
    finally:
        db.close()


def test_migrate_is_idempotent():
    """It runs on every boot; a second pass must not fail with "duplicate column name"."""
    _rebuild_legacy_table()
    _migrate()
    _migrate()

    assert _columns("mcp_servers").count("disabled_tools") == 1


def test_every_model_column_exists_in_the_table_after_migrating():
    """The general form of the outage: a model column with no column in the database. Catches
    the next one without anyone having to remember this file exists."""
    _rebuild_legacy_table()
    _migrate()

    for table_name, table in models.Base.metadata.tables.items():
        actual = set(_columns(table_name))
        missing = {c.name for c in table.columns} - actual
        assert not missing, f"{table_name} is missing {missing} — add an ALTER TABLE to _migrate()"
