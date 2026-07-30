"""v16 duplicados es informativo sin unique constraints

Revision ID: 585877974ab1
Revises: e6c8a4276be2
Create Date: 2026-07-30 13:17:08.991084

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '585877974ab1'
down_revision: Union[str, Sequence[str], None] = 'e6c8a4276be2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    V-16 (§12 del funcional) trata los duplicados como INFORMATIVO: se
    detectan y reportan (validador, Etapa 8), no se bloquean a nivel de
    esquema — de ahí que se saquen los unique constraints puestos en la
    migración inicial.

    `batch_alter_table` porque SQLite no soporta ALTER de constraints
    directamente (solo relevante para el SQLite de desarrollo/tests — en
    Postgres esto se traduce a un DROP CONSTRAINT normal).
    """
    with op.batch_alter_table('venta_ecom', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_venta_ecom_numero_orden'))
        batch_op.create_index(batch_op.f('ix_venta_ecom_numero_orden'), ['numero_orden'], unique=False)

    with op.batch_alter_table('venta_tactica', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('uq_venta_tactica_comprobante_sku'), type_='unique')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('venta_tactica', schema=None) as batch_op:
        batch_op.create_unique_constraint(batch_op.f('uq_venta_tactica_comprobante_sku'), ['nro_factura', 'codigo'])

    with op.batch_alter_table('venta_ecom', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_venta_ecom_numero_orden'))
        batch_op.create_index(batch_op.f('ix_venta_ecom_numero_orden'), ['numero_orden'], unique=True)
