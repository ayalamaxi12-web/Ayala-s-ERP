"""motor de precios: parámetros con vigencia, carga del PM y logística por SKU

Revision ID: e7f8a9b0c1d2
Revises: d4e5f6a7b8c9
Create Date: 2026-09-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MONEY = sa.Numeric(18, 6)
_FACTOR = sa.Numeric(10, 6)


def _alta():
    return [
        sa.Column('vigente_desde', sa.Date(), nullable=False),
        sa.Column('cargado_por', sa.String(length=128), nullable=False),
        sa.Column('cargado_en', sa.DateTime(), nullable=False),
    ]


def upgrade() -> None:
    """Etapa 1 del motor de precios (diseño aprobado por Maxx, 2026-09-29):
    el motor lee sus parámetros de la base — nada hardcodeado — y cada
    cambio queda como fila nueva con vigencia y quién lo cargó."""
    op.create_table(
        'pricing_parametro',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('canal', sa.String(length=16), nullable=False),
        sa.Column('clave', sa.String(length=64), nullable=False),
        sa.Column('valor', _MONEY, nullable=False),
        sa.Column('descripcion', sa.String(length=255), nullable=True),
        *_alta(),
    )
    op.create_index('ix_pricing_parametro_canal', 'pricing_parametro', ['canal'])
    op.create_index('ix_pricing_parametro_clave', 'pricing_parametro', ['clave'])

    op.create_table(
        'pricing_comision_categoria',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('canal', sa.String(length=16), nullable=False),
        sa.Column('categoria', sa.String(length=128), nullable=False),
        sa.Column('pct', _FACTOR, nullable=False),
        sa.Column('origen', sa.String(length=128), nullable=True),
        *_alta(),
    )
    op.create_index('ix_pricing_comision_categoria_canal', 'pricing_comision_categoria', ['canal'])

    op.create_table(
        'pricing_cuotas',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('canal', sa.String(length=16), nullable=False),
        sa.Column('plan', sa.String(length=16), nullable=False),
        sa.Column('pct', _FACTOR, nullable=False),
        *_alta(),
    )
    op.create_index('ix_pricing_cuotas_canal', 'pricing_cuotas', ['canal'])

    op.create_table(
        'pricing_tramo',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tabla', sa.String(length=64), nullable=False),
        sa.Column('unidad', sa.String(length=8), nullable=False),
        sa.Column('desde', _MONEY, nullable=False),
        sa.Column('hasta', _MONEY, nullable=True),
        sa.Column('valor', _MONEY, nullable=False),
        *_alta(),
    )
    op.create_index('ix_pricing_tramo_tabla', 'pricing_tramo', ['tabla'])

    op.create_table(
        'pricing_sku',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('sku', sa.String(length=64), nullable=False),
        sa.Column('precio_web', _MONEY, nullable=True),
        sa.Column('forma_pago_web', sa.String(length=16), nullable=True),
        sa.Column('pct_ml', _FACTOR, nullable=True),
        sa.Column('condicion_ml', sa.String(length=16), nullable=True),
        sa.Column('precio_fravega', _MONEY, nullable=True),
        sa.Column('precio_megatone', _MONEY, nullable=True),
        sa.Column('precio_oncity', _MONEY, nullable=True),
        sa.Column('motivo', sa.String(length=255), nullable=True),
        *_alta(),
    )
    op.create_index('ix_pricing_sku_sku', 'pricing_sku', ['sku'])

    op.create_table(
        'pricing_sku_logistica',
        sa.Column('sku', sa.String(length=64), primary_key=True),
        sa.Column('peso_kg', _MONEY, nullable=True),
        sa.Column('alto_cm', _MONEY, nullable=True),
        sa.Column('ancho_cm', _MONEY, nullable=True),
        sa.Column('largo_cm', _MONEY, nullable=True),
        sa.Column('origen', sa.String(length=64), nullable=True),
        sa.Column('actualizado_en', sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('pricing_sku_logistica')
    op.drop_index('ix_pricing_sku_sku', table_name='pricing_sku')
    op.drop_table('pricing_sku')
    op.drop_index('ix_pricing_tramo_tabla', table_name='pricing_tramo')
    op.drop_table('pricing_tramo')
    op.drop_index('ix_pricing_cuotas_canal', table_name='pricing_cuotas')
    op.drop_table('pricing_cuotas')
    op.drop_index('ix_pricing_comision_categoria_canal', table_name='pricing_comision_categoria')
    op.drop_table('pricing_comision_categoria')
    op.drop_index('ix_pricing_parametro_clave', table_name='pricing_parametro')
    op.drop_index('ix_pricing_parametro_canal', table_name='pricing_parametro')
    op.drop_table('pricing_parametro')
