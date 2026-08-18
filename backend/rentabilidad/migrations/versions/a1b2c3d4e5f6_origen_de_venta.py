"""origen de venta_tactica/venta_ecom (motor vs importado_sheet)

Revision ID: a1b2c3d4e5f6
Revises: 36efbaaca39f
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '36efbaaca39f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Trazabilidad de origen por fila (pedido de Maxx, 2026-08-18) -- "motor"
    para lo calculado en vivo (SQL/API), "importado_sheet" para la migración
    histórica de las pestañas viejas del Sheet."""
    op.add_column('venta_tactica', sa.Column('origen', sa.String(length=32), nullable=False, server_default='motor'))
    op.add_column('venta_ecom', sa.Column('origen', sa.String(length=32), nullable=False, server_default='motor'))


def downgrade() -> None:
    op.drop_column('venta_ecom', 'origen')
    op.drop_column('venta_tactica', 'origen')
