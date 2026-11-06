"""alerta diaria de pedidos pendientes de Táctica: corridas e historial por pedido

Revision ID: k5f6a7b8c9d0
Revises: j4e5f6a7b8c9
Create Date: 2026-11-06 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'k5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'j4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tactica_pendiente_corrida',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('fecha', sa.Date(), nullable=False, unique=True),
        sa.Column('ejecutada_en', sa.DateTime(), nullable=False),
        sa.Column('estado', sa.String(length=8), nullable=False),
        sa.Column('total_pendientes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('parados', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_msg', sa.Text(), nullable=True),
    )
    op.create_index('ix_tactica_pendiente_corrida_fecha', 'tactica_pendiente_corrida', ['fecha'])
    op.create_table(
        'tactica_pendiente',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('nro_pedido', sa.Integer(), nullable=False),
        sa.Column('cliente', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('vendedor', sa.String(length=120), nullable=False, server_default=''),
        sa.Column('monto', sa.Numeric(18, 6), nullable=False, server_default='0'),
        sa.Column('moneda', sa.String(length=8), nullable=False, server_default=''),
        sa.Column('skus', sa.Text(), nullable=False, server_default=''),
        sa.Column('dias_parado', sa.Integer(), nullable=False),
        sa.Column('ultimo_movimiento', sa.DateTime(), nullable=True),
        sa.Column('creado', sa.DateTime(), nullable=True),
        sa.Column('nivel', sa.String(length=16), nullable=False),
        sa.UniqueConstraint('fecha', 'nro_pedido', name='uq_tactica_pendiente_dia_pedido'),
    )
    op.create_index('ix_tactica_pendiente_fecha', 'tactica_pendiente', ['fecha'])
    op.create_index('ix_tactica_pendiente_nro_pedido', 'tactica_pendiente', ['nro_pedido'])


def downgrade() -> None:
    op.drop_table('tactica_pendiente')
    op.drop_table('tactica_pendiente_corrida')
