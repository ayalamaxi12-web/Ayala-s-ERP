"""venta_ecom: unidades, cuotas y cargo por cuotas del vendedor

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-10-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Reporte de desvío de precios (Maca, 2026-10-03): para comparar el
    margen real de cada venta con el proyectado hace falta saber cuántas
    unidades, en cuántas cuotas y cuánto cobró el canal por las cuotas sin
    interés. Nullable: filas del Excel / anteriores no traen el dato (la
    corrida diaria recalcula el ciclo completo y las completa)."""
    with op.batch_alter_table('venta_ecom') as batch_op:
        batch_op.add_column(sa.Column('unidades', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('cuotas', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('cargo_cuotas', sa.Numeric(18, 6), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('venta_ecom') as batch_op:
        batch_op.drop_column('cargo_cuotas')
        batch_op.drop_column('cuotas')
        batch_op.drop_column('unidades')
