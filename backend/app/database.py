import json

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DB_PATH


class Base(DeclarativeBase):
    pass


engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


# SQLite foreign-key enforcement is OFF by default and must be enabled per connection —
# without it the ondelete=CASCADE in the models never fires (bulk deletes leave orphan rows).
@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401 register models on Base

    Base.metadata.create_all(bind=engine)
    _migrate()


def _migrate():
    """Minimal SQLite migration: adds missing columns via ALTER TABLE (for existing DBs)."""
    with engine.connect() as conn:
        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(chats)").fetchall()]
        if "pinned" not in cols:
            conn.exec_driver_sql("ALTER TABLE chats ADD COLUMN pinned BOOLEAN NOT NULL DEFAULT 0")
        if "user_id" not in cols:
            # Existing (single-user) chats are attached to the super admin (id=1, the first sign-up).
            conn.exec_driver_sql("ALTER TABLE chats ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")

        # Create the single settings row if absent (registration open by default).
        conn.exec_driver_sql(
            "INSERT INTO settings (id, registration_enabled) VALUES (1, 1) "
            "ON CONFLICT(id) DO NOTHING"
        )

        scols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(servers)").fetchall()]
        if "type" not in scols:
            conn.exec_driver_sql("ALTER TABLE servers ADD COLUMN type VARCHAR(20) NOT NULL DEFAULT 'ollama'")
        if "base_url" not in scols:
            conn.exec_driver_sql("ALTER TABLE servers ADD COLUMN base_url VARCHAR(500)")
        if "api_key" not in scols:
            conn.exec_driver_sql("ALTER TABLE servers ADD COLUMN api_key VARCHAR(500)")

        # `create_all` creates missing TABLES, never missing COLUMNS — a column added to a table
        # that already exists in a deployed DB needs an ALTER here or the app dies on the first
        # query (it did, in production: "no such column: mcp_servers.disabled_tools" → 502).
        # PRAGMA returns nothing for a table that does not exist yet, hence the truthiness check.
        mcpcols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(mcp_servers)").fetchall()]
        if mcpcols and "disabled_tools" not in mcpcols:
            conn.exec_driver_sql("ALTER TABLE mcp_servers ADD COLUMN disabled_tools JSON")
        if mcpcols and "tool_modes" not in mcpcols:
            conn.exec_driver_sql("ALTER TABLE mcp_servers ADD COLUMN tool_modes JSON")
            # disabled_tools (one release old) becomes {name: "off"}. The old column is left in
            # place — SQLite DROP COLUMN is not worth the risk for a harmless orphan.
            for row in conn.exec_driver_sql(
                "SELECT id, disabled_tools FROM mcp_servers WHERE disabled_tools IS NOT NULL"
            ).fetchall():
                names = json.loads(row[1] or "[]")
                if names:
                    conn.exec_driver_sql(
                        "UPDATE mcp_servers SET tool_modes = ? WHERE id = ?",
                        (json.dumps({n: "off" for n in names}), row[0]),
                    )

        mcols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(messages)").fetchall()]
        if "tokens_per_sec" not in mcols:
            conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN tokens_per_sec FLOAT")
        if "images" not in mcols:
            conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN images JSON")
        if "attachments" not in mcols:
            conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN attachments JSON")
        conn.commit()
