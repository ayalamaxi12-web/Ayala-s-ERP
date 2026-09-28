"""venta_ecom.es_full (orden despachada por ML Full)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """El adaptador de la API ya sabía qué órdenes son Full (lo usa para el
    costo de envío) pero no lo guardaba; el reporte diario lo necesita para
    el bloque "Full" (pedido de Maxx, 2026-09-29). Nullable: las filas
    importadas de la planilla no traen el dato."""
    with op.batch_alter_table('venta_ecom') as batch_op:
        batch_op.add_column(sa.Column('es_full', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('venta_ecom') as batch_op:
        batch_op.drop_column('es_full')
