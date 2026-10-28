"""Create missing tables and harden product/category schema.

Revision ID: 20260822_01
Revises: None
"""

import sqlalchemy as sa
from alembic import op

revision = "20260822_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    from wxcloudrun import db

    db.metadata.create_all(bind=bind)
    inspector = sa.inspect(bind)
    product_columns = {column["name"] for column in inspector.get_columns("products")}
    if "product_english_name" not in product_columns:
        op.add_column("products", sa.Column("product_english_name", sa.String(200), nullable=True))

    inspector = sa.inspect(bind)
    category_uniques = inspector.get_unique_constraints("categories")
    category_indexes = inspector.get_indexes("categories")
    has_unique_name = any(
        constraint.get("column_names") == ["name"] for constraint in category_uniques
    ) or any(
        index.get("unique") and index.get("column_names") == ["name"] for index in category_indexes
    )
    if not has_unique_name:
        duplicates = (
            bind.execute(
                sa.text(
                    "SELECT name, COUNT(*) AS count FROM categories "
                    "GROUP BY name HAVING COUNT(*) > 1 LIMIT 5"
                )
            )
            .mappings()
            .all()
        )
        if duplicates:
            names = ", ".join(row["name"] for row in duplicates)
            raise RuntimeError(f"categories存在重名，无法添加唯一约束: {names}")
        op.create_unique_constraint("uq_categories_name", "categories", ["name"])


def downgrade():
    # Data-preserving migration: columns/constraints are intentionally retained.
    pass
