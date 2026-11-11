"""alerta de pedidos pendientes de Táctica: guardar el «Escenario» de cada pedido (etapa del circuito)

Revision ID: l6a7b8c9d0e1
Revises: k5f6a7b8c9d0
Create Date: 2026-11-11 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'l6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'k5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tactica_pendiente', sa.Column('escenario', sa.String(length=120), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('tactica_pendiente', 'escenario')
