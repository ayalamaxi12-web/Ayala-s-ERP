"""venta_ecom.skus_vendidos sin tope de largo (Text)

Revision ID: f1a2b3c4d5e6
Revises: e7f8a9b0c1d2
Create Date: 2026-10-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Bug real (corridas del 02 y 03/10/2026): una orden con muchos SKU
    superó los 1000 caracteres de `skus_vendidos`, Postgres rechazó el
    INSERT y la corrida diaria no guardó nada — el reporte salió en $0."""
    with op.batch_alter_table('venta_ecom') as batch_op:
        batch_op.alter_column('skus_vendidos', existing_type=sa.String(length=1000), type_=sa.Text(),
                              existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table('venta_ecom') as batch_op:
        batch_op.alter_column('skus_vendidos', existing_type=sa.Text(), type_=sa.String(length=1000),
                              existing_nullable=False)
