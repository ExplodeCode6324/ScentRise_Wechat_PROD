"""Exercise synthetic legacy schemas only inside the disposable Issue #4 CI sandbox."""

from __future__ import annotations

import os
import sys

import sqlalchemy as sa

ALLOWED_DATABASES = {"scentrise_ci_empty", "scentrise_ci_legacy", "scentrise_ci_duplicates"}


def main():
    url = sa.engine.make_url(os.environ.get("DATABASE_URL", "sqlite://"))
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("CI_SANDBOX") != "issue4"
        or url.drivername != "mysql+pymysql"
        or url.host != "127.0.0.1"
        or url.database not in ALLOWED_DATABASES
    ):
        raise SystemExit("Refusing writes outside the explicit disposable Issue #4 CI sandbox")
    os.environ.update(
        TESTING="1",
        JWT_SECRET="issue4-ci-only-secret-over-thirty-two-bytes",
        AUTO_CREATE_DATABASE="0",
        AUTO_CREATE_TABLES="0",
    )
    server = sa.create_engine(url.set(database=None), isolation_level="AUTOCOMMIT")
    with server.connect() as connection:
        # The database identifier is checked against the fixed allowlist above.
        connection.execute(sa.text(f"CREATE DATABASE `{url.database}` CHARACTER SET utf8mb4"))
    server.dispose()

    from flask_migrate import upgrade

    from wxcloudrun import app, db

    duplicate_case = url.database == "scentrise_ci_duplicates"
    with app.app_context():
        if url.database != "scentrise_ci_empty":
            # Synthetic old shape, never copied from production data or an environment file.
            db.create_all()
            unique = next(
                item["name"]
                for item in sa.inspect(db.engine).get_unique_constraints("categories")
                if item["column_names"] == ["name"]
            )
            assert unique.isidentifier()
            with db.engine.begin() as connection:
                connection.execute(sa.text(f"ALTER TABLE categories DROP INDEX `{unique}`"))
                connection.execute(sa.text("ALTER TABLE products DROP COLUMN product_english_name"))
                connection.execute(sa.text("INSERT INTO categories (name) VALUES ('ci-series')"))
                if duplicate_case:
                    connection.execute(
                        sa.text("INSERT INTO categories (name) VALUES ('ci-series')")
                    )
        try:
            upgrade()
        except RuntimeError as error:
            if not duplicate_case or "categories存在重名" not in str(error):
                raise
            with db.engine.connect() as connection:
                assert connection.scalar(sa.text("SELECT COUNT(*) FROM categories")) == 2
            print("PASS duplicate legacy categories block migration without deleting rows")
            return
        assert not duplicate_case, "duplicate categories unexpectedly passed the migration"
        with db.engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "20260822_01"
            )
        columns = {item["name"] for item in sa.inspect(db.engine).get_columns("products")}
        assert "product_english_name" in columns
        assert any(
            item["column_names"] == ["name"]
            for item in sa.inspect(db.engine).get_unique_constraints("categories")
        )
        client = app.test_client()
        for path in ("/healthz", "/readyz", "/api/categories", "/api/products", "/admin/"):
            response = client.get(path)
            assert response.status_code == 200, (path, response.status_code)
    print(f"PASS {url.database}: migration + candidate read routes")
    print("This is synthetic compatibility coverage, not production schema/rollback approval.")


if __name__ == "__main__":
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    main()
