"""foto guardada de los módulos de Mercado Libre, alertas persistentes y caché de lotes

Revision ID: j4e5f6a7b8c9
Revises: i3d4e5f6a7b8
Create Date: 2026-10-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'j4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'i3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(JSONB(), 'postgresql')


def upgrade() -> None:
    op.create_table(
        'ml_foto',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('modulo', sa.String(length=32), nullable=False),
        sa.Column('cuenta', sa.String(length=16), nullable=False),
        sa.Column('params', sa.String(length=64), nullable=False),
        sa.Column('obtenido_en', sa.DateTime(), nullable=True),
        sa.Column('estado', sa.String(length=16), nullable=True),
        sa.Column('incompletos', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('duracion_seg', sa.Numeric(18, 6), nullable=True),
        sa.Column('payload', _JSON, nullable=True),
        sa.Column('error_msg', sa.Text(), nullable=True),
        sa.Column('error_en', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('modulo', 'cuenta', 'params', name='uq_ml_foto_clave'),
    )
    op.create_table(
        'ml_alerta',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('modulo', sa.String(length=32), nullable=False),
        sa.Column('tipo', sa.String(length=48), nullable=False),
        sa.Column('clave', sa.String(length=128), nullable=False),
        sa.Column('primera_vez', sa.DateTime(), nullable=False),
        sa.Column('ultima_vez', sa.DateTime(), nullable=False),
        sa.Column('estado', sa.String(length=16), nullable=False),
        sa.Column('vista_en', sa.DateTime(), nullable=True),
        sa.Column('detalle', _JSON, nullable=True),
        sa.UniqueConstraint('modulo', 'tipo', 'clave', name='uq_ml_alerta_clave'),
    )
    op.create_index('ix_ml_alerta_modulo', 'ml_alerta', ['modulo'])
    op.create_table(
        'ml_lote_cache',
        sa.Column('clave', sa.String(length=40), primary_key=True),
        sa.Column('obtenido_en', sa.DateTime(), nullable=False),
        sa.Column('payload', _JSON, nullable=False),
    )
    op.create_index('ix_ml_lote_cache_obtenido_en', 'ml_lote_cache', ['obtenido_en'])


def downgrade() -> None:
    op.drop_index('ix_ml_lote_cache_obtenido_en', table_name='ml_lote_cache')
    op.drop_table('ml_lote_cache')
    op.drop_index('ix_ml_alerta_modulo', table_name='ml_alerta')
    op.drop_table('ml_alerta')
    op.drop_table('ml_foto')
