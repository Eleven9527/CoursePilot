from contextlib import contextmanager
import sqlite3

from app.core.config import settings


class PostgresConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=()):
        return self.connection.execute(sql.replace("?", "%s"), params)

    def executemany(self, sql, params):
        with self.connection.cursor() as cursor:
            cursor.executemany(sql.replace("?", "%s"), params)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()


@contextmanager
def connect():
    if settings.database_url:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(settings.database_url, row_factory=dict_row, connect_timeout=5) as connection:
            yield PostgresConnection(connection)
    else:
        connection = sqlite3.connect(settings.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()


def begin_write(connection):
    if isinstance(connection, PostgresConnection):
        # Serialize queue transitions across workers before reading mutable task state.
        connection.execute("SELECT pg_advisory_xact_lock(671728591)")
    else:
        connection.execute("BEGIN IMMEDIATE")
