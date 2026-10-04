"""último TC del BNA guardado (respaldo cuando el BNA no responde)

Revision ID: g1b2c3d4e5f6
Revises: b3c4d5e6f7a8
Create Date: 2026-10-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tc_bna_guardado',
        sa.Column('id', sa.String(length=16), primary_key=True),
        sa.Column('valor', sa.Numeric(18, 6), nullable=False),
        sa.Column('obtenido_en', sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('tc_bna_guardado')
