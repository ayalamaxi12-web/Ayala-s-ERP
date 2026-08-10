"""cierre rentabilidad metadata

Revision ID: 36efbaaca39f
Revises: 4c5269917b66
Create Date: 2026-08-10 10:11:56.742099

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36efbaaca39f'
down_revision: Union[str, Sequence[str], None] = '4c5269917b66'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Metadata de cierres guardados (§3 del ajuste de arquitectura,
    2026-08-10) — no toca ninguna tabla de hechos ni de parámetros."""
    op.create_table('cierre_rentabilidad',
    sa.Column('periodo', sa.String(length=64), nullable=False),
    sa.Column('desde', sa.Date(), nullable=False),
    sa.Column('hasta', sa.Date(), nullable=False),
    sa.Column('generado_en', sa.DateTime(), nullable=False),
    sa.Column('tactica_guardado', sa.Boolean(), nullable=False),
    sa.Column('ecom_guardado', sa.Boolean(), nullable=False),
    sa.Column('ecom_origen', sa.String(length=16), nullable=True),
    sa.PrimaryKeyConstraint('periodo')
    )


def downgrade() -> None:
    op.drop_table('cierre_rentabilidad')
