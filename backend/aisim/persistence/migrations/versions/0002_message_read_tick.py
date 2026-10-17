"""messages.read_tick: when the recipient read each message

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('read_tick', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'read_tick')
