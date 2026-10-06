"""Add login lockout fields

Revision ID: 1efbfce38922
Revises: 
Create Date: 2026-10-06 16:55:41.762465

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1efbfce38922'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    with op.batch_alter_table("users") as batch_op:
        if "failed_login_attempts" not in columns:
            batch_op.add_column(
                sa.Column(
                    "failed_login_attempts",
                    sa.Integer(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )
        if "login_locked_until" not in columns:
            batch_op.add_column(sa.Column("login_locked_until", sa.DateTime(), nullable=True))


def downgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    with op.batch_alter_table("users") as batch_op:
        if "login_locked_until" in columns:
            batch_op.drop_column("login_locked_until")
        if "failed_login_attempts" in columns:
            batch_op.drop_column("failed_login_attempts")
