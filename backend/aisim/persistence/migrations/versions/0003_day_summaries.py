"""day_summaries: the daily chronicle

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.create_table(
        'day_summaries',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('world_id', sa.String(length=32), nullable=False),
        sa.Column('day', sa.Integer(), nullable=False),
        sa.Column('from_tick', sa.Integer(), nullable=False),
        sa.Column('to_tick', sa.Integer(), nullable=False),
        sa.Column('headline', sa.Text(), nullable=False),
        sa.Column('story', sa.Text(), nullable=False),
        sa.Column('notable', JSONType, nullable=False),
        sa.Column('narrator', sa.String(length=20), nullable=False),
        sa.Column('model', sa.String(length=120), nullable=True),
        sa.Column('digest', JSONType, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['world_id'], ['worlds.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_day_summaries_world_day', 'day_summaries', ['world_id', 'day'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_day_summaries_world_day', table_name='day_summaries')
    op.drop_table('day_summaries')
