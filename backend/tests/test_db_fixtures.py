"""Aislamiento real de la fixture `db_session` (rollback por test)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_a_inserta_y_ve_su_fila(db_session: AsyncSession) -> None:
    await db_session.execute(text("CREATE TABLE sonda_rollback (n int)"))
    await db_session.execute(text("INSERT INTO sonda_rollback VALUES (1)"))
    total = (await db_session.execute(text("SELECT count(*) FROM sonda_rollback"))).scalar_one()
    assert total == 1


async def test_b_no_ve_lo_insertado_por_a(db_session: AsyncSession) -> None:
    existe = (
        await db_session.execute(text("SELECT to_regclass('public.sonda_rollback')"))
    ).scalar_one()
    assert existe is None
