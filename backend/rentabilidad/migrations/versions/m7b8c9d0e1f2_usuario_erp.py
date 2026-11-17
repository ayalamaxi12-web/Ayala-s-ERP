"""usuarios del ERP con login propio y accesos por módulo

Revision ID: m7b8c9d0e1f2
Revises: l6a7b8c9d0e1
Create Date: 2026-11-17 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'm7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'l6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'usuario_erp',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('usuario', sa.String(length=40), nullable=False),
        sa.Column('nombre', sa.String(length=80), nullable=False, server_default=''),
        sa.Column('rol', sa.String(length=16), nullable=False, server_default='usuario'),
        sa.Column('modulos', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('pass_hash', sa.String(length=200), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('version_sesion', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('creado', sa.DateTime(), nullable=True),
        sa.Column('ultimo_ingreso', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_usuario_erp_usuario', 'usuario_erp', ['usuario'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_usuario_erp_usuario', table_name='usuario_erp')
    op.drop_table('usuario_erp')
