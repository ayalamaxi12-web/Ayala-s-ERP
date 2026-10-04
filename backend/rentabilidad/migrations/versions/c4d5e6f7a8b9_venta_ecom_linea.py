"""venta_ecom_linea: importe real por SKU de cada orden

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-10-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Combos/kits/carritos: el desglose por SKU atribuía la orden entera a
    la combinación de SKU (y al PM del primero). La API de Ecom trae el
    importe de cada línea; se guarda acá. `venta_ecom` (el total de la
    orden) no se toca. Las órdenes ya guardadas no tienen líneas hasta que
    la corrida diaria recalcula el ciclo."""
    op.create_table(
        'venta_ecom_linea',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('venta_id', sa.String(36), sa.ForeignKey('venta_ecom.id', ondelete='CASCADE'), nullable=False),
        sa.Column('periodo', sa.String(64), nullable=False),
        sa.Column('orden_linea', sa.Integer(), nullable=False),
        sa.Column('sku', sa.String(100), nullable=False),
        sa.Column('cantidad', sa.Integer(), nullable=False),
        sa.Column('precio_final', sa.Numeric(18, 6), nullable=False),
        sa.Column('precio_sin_iva', sa.Numeric(18, 6), nullable=False),
        sa.Column('costo_sin_iva', sa.Numeric(18, 6), nullable=False),
        sa.Column('factor_iva', sa.Numeric(10, 6), nullable=True),
        sa.Column('pm', sa.String(100), nullable=True),
        sa.Column('subcategoria', sa.String(255), nullable=True),
        sa.Column('categoria', sa.String(255), nullable=True),
        sa.Column('subcategoria2', sa.String(255), nullable=True),
        sa.Column('item_ml', sa.String(32), nullable=True),
        sa.Column('permalink_ml', sa.Text(), nullable=True),
    )
    op.create_index('ix_venta_ecom_linea_venta_id', 'venta_ecom_linea', ['venta_id'])
    op.create_index('ix_venta_ecom_linea_periodo', 'venta_ecom_linea', ['periodo'])


def downgrade() -> None:
    op.drop_index('ix_venta_ecom_linea_periodo', table_name='venta_ecom_linea')
    op.drop_index('ix_venta_ecom_linea_venta_id', table_name='venta_ecom_linea')
    op.drop_table('venta_ecom_linea')
