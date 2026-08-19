"""ensanchar venta_tactica.tipo_factura (10 -> 120)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """10 caracteres alcanzaba para un código corto (FEA/CVA/etc.) pero la
    migración histórica del Sheet (2026-08-19) trae el texto completo de
    "Tipo de Factura" tal cual viene cargado ahí (hasta 79 caracteres
    confirmados, ej. "MLA - Multipropósito (Factura-Nota de Crédito-Nota
    de Débito) - Nota de Crédito") -- pasaba inadvertido en SQLite (no
    valida longitud de VARCHAR), recién se vio el error real contra
    Postgres. `batch_alter_table` (no `alter_column` directo) porque SQLite
    -- usado por la suite de tests -- no soporta ALTER COLUMN ... TYPE."""
    with op.batch_alter_table('venta_tactica') as batch_op:
        batch_op.alter_column('tipo_factura', type_=sa.String(length=120))


def downgrade() -> None:
    with op.batch_alter_table('venta_tactica') as batch_op:
        batch_op.alter_column('tipo_factura', type_=sa.String(length=10))
