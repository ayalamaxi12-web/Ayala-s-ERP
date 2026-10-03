"""venta_ecom: publicación de ML exacta de la venta (MLA y link)

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-10-03 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Reporte de Maca (2026-10-03): el link a la publicación tiene que ser
    el de la venta, no uno adivinado por SKU (un SKU puede estar en varias
    publicaciones). La orden de Ecom lo trae en `OrderList.listing`."""
    with op.batch_alter_table('venta_ecom') as batch_op:
        batch_op.add_column(sa.Column('item_ml', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('permalink_ml', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('venta_ecom') as batch_op:
        batch_op.drop_column('permalink_ml')
        batch_op.drop_column('item_ml')
