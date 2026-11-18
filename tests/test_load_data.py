from sqlalchemy import text

from scripts.load_data import TABLES, counts, purge, seed


def snapshot(conn):
    return {
        table: conn.scalar(
            text(
                "SELECT md5(coalesce(string_agg(x::text, '|' "
                f"ORDER BY x::text), '')) FROM {table} x"
            )
        )
        for table in TABLES
    }


def test_load_data_is_removed_exactly(test_database, active_rental):
    with test_database.begin() as conn:
        before = snapshot(conn)
        seed(conn, "pytest", 0.01)
        created = counts(conn, "pytest")
        assert created["tickets"] == 500
        assert created["ticket_messages"] == 1500
        assert created["activity"] == 2000
        # A second data set with another tag stays separate.
        seed(conn, "other", 0.01)
        purge(conn, "pytest")
        assert not any(counts(conn, "pytest").values())
        assert counts(conn, "other") == created
        purge(conn, "other")
        assert snapshot(conn) == before
