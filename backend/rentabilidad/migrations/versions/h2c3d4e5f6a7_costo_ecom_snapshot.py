"""foto del catálogo de costos de Ecom (el backend la lee en vez de bajar el catálogo en cada request)

Revision ID: h2c3d4e5f6a7
Revises: g1b2c3d4e5f6
Create Date: 2026-10-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'g1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'costo_ecom_snapshot',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('obtenido_en', sa.DateTime(), nullable=False),
        sa.Column('origen', sa.String(length=16), nullable=False),
        sa.Column('duracion_seg', sa.Numeric(18, 6), nullable=False),
        sa.Column('cantidad', sa.Integer(), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
    )
    op.create_index('ix_costo_ecom_snapshot_obtenido_en', 'costo_ecom_snapshot', ['obtenido_en'])


def downgrade() -> None:
    op.drop_index('ix_costo_ecom_snapshot_obtenido_en', table_name='costo_ecom_snapshot')
    op.drop_table('costo_ecom_snapshot')
