"""snapshots versionados del tablero Proyección de compras e inversión 2027 (solo lectura)

Revision ID: i3d4e5f6a7b8
Revises: h2c3d4e5f6a7
Create Date: 2026-10-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'i3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'h2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'proyeccion_snapshot',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('subido_en', sa.DateTime(), nullable=False),
        sa.Column('generado', sa.String(length=32), nullable=False),
        sa.Column('schema_version', sa.String(length=16), nullable=False),
        sa.Column('tamano_bytes', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON().with_variant(JSONB(), 'postgresql'), nullable=False),
    )
    op.create_index('ix_proyeccion_snapshot_subido_en', 'proyeccion_snapshot', ['subido_en'])


def downgrade() -> None:
    op.drop_index('ix_proyeccion_snapshot_subido_en', table_name='proyeccion_snapshot')
    op.drop_table('proyeccion_snapshot')
