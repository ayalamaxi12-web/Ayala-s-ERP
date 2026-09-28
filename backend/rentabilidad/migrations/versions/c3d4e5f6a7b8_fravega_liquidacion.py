"""venta_ecom: orden_externa/origen_comision/observacion + liquidacion_fravega + TC del cierre

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Integración Ecom por API con las reglas aprobadas por Maxx
    (2026-09-27): Frávega se calcula con comisión estimada hasta que llega
    su liquidación quincenal, y ahí se reemplaza por la real — hace falta
    saber qué orden de Frávega es cada venta (`orden_externa`), si su
    comisión es estimada o real (`origen_comision`) y guardar la
    liquidación (`liquidacion_fravega`) para que un cierre re-guardado no
    vuelva al estimado."""
    with op.batch_alter_table('venta_ecom') as batch_op:
        batch_op.add_column(sa.Column('orden_externa', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('origen_comision', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('observacion', sa.String(length=255), nullable=True))
        batch_op.create_index('ix_venta_ecom_orden_externa', ['orden_externa'])

    op.create_table(
        'liquidacion_fravega',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('orden', sa.String(length=64), nullable=False),
        sa.Column('valor_sku', sa.Numeric(18, 6), nullable=False),
        sa.Column('comision', sa.Numeric(18, 6), nullable=False),
        sa.Column('fee_logistico', sa.Numeric(18, 6), nullable=False),
        sa.Column('liquidacion_desde', sa.Date(), nullable=False),
        sa.Column('liquidacion_hasta', sa.Date(), nullable=False),
        sa.Column('archivo', sa.String(length=255), nullable=True),
        sa.Column('cargado_en', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_liquidacion_fravega_orden', 'liquidacion_fravega', ['orden'])

    # TC usado en el último guardado de Ecom (y su origen), para mostrarlo en
    # el informe (pedido de Maxx, 2026-09-28).
    with op.batch_alter_table('cierre_rentabilidad') as batch_op:
        batch_op.add_column(sa.Column('tc_ecom', sa.Numeric(18, 6), nullable=True))
        batch_op.add_column(sa.Column('tc_ecom_origen', sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('cierre_rentabilidad') as batch_op:
        batch_op.drop_column('tc_ecom_origen')
        batch_op.drop_column('tc_ecom')
    op.drop_index('ix_liquidacion_fravega_orden', table_name='liquidacion_fravega')
    op.drop_table('liquidacion_fravega')
    with op.batch_alter_table('venta_ecom') as batch_op:
        batch_op.drop_index('ix_venta_ecom_orden_externa')
        batch_op.drop_column('observacion')
        batch_op.drop_column('origen_comision')
        batch_op.drop_column('orden_externa')
