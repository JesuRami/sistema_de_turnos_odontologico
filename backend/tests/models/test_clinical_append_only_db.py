"""Append-only clínico (D1; Ley 26.529, reglas 7 y 9) contra Postgres real.

Dos barreras independientes por tabla: el trigger `BEFORE UPDATE OR DELETE` (rechaza incluso al
dueño del schema) y la falta de `UPDATE`/`DELETE` del rol `app_writer` (C-14). La prueba de
punta a punta con un usuario de login real vive en `test_app_writer_role_db.py`, parametrizada
sobre `APPEND_ONLY_TABLES`. Escenarios: "Versiones inmutables", "Inmutabilidad", "Historial
inmutable", "Bitácora inmutable", "Sin DELETE".
"""

from __future__ import annotations

from typing import Any

import pytest
from app.ops.db_privileges import APP_ROLE, APPEND_ONLY_TABLES
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.models.test_clinical_schema_db import HASH, INICIO, _escena, _sql

pytestmark = pytest.mark.integration

CLINICAL_APPEND_ONLY = (
    "clinical_record",
    "anamnesis_version",
    "odontogram_event",
    "clinical_evolution",
    "clinical_attachment",
    "clinical_attachment_removal",
    "treatment_plan",
    "treatment_plan_version",
    "treatment_plan_item",
    "treatment_plan_decision",
    "clinical_access_event",
)


async def _una_fila_por_tabla(session: AsyncSession) -> dict[str, Any]:
    e = await _escena(session)
    p = {"c": e.clinic_id, "r": e.record_id, "u": e.user_id, "pr": e.professional_id}
    ids: dict[str, Any] = {"clinical_record": e.record_id}
    ids["anamnesis_version"] = await _sql(
        session,
        "INSERT INTO anamnesis_version (clinic_id, record_id, version, answers, "
        "created_by_user_id) VALUES (:c, :r, 1, '{}'::jsonb, :u) RETURNING id",
        p,
    )
    ids["odontogram_event"] = await _sql(
        session,
        "INSERT INTO odontogram_event (clinic_id, record_id, tooth, surface, professional_id, "
        "created_by_user_id) VALUES (:c, :r, 36, 'O', :pr, :u) RETURNING id",
        p,
    )
    ids["clinical_evolution"] = await _sql(
        session,
        "INSERT INTO clinical_evolution (clinic_id, record_id, professional_id, "
        "created_by_user_id, kind, body, signed_at, content_sha256) "
        "VALUES (:c, :r, :pr, :u, 'entry', 'Evolución sintética', :now, :h) RETURNING id",
        {**p, "now": INICIO, "h": HASH},
    )
    ids["clinical_attachment"] = await _sql(
        session,
        "INSERT INTO clinical_attachment (clinic_id, record_id, kind, content_type, size_bytes, "
        "sha256, display_name, storage_key, created_by_user_id) VALUES (:c, :r, 'photo', "
        "'image/png', 10, :h, 'foto.png', :k, :u) RETURNING id",
        {**p, "h": HASH, "k": f"{e.clinic_id}/clave-sintetica"},
    )
    ids["clinical_attachment_removal"] = await _sql(
        session,
        "INSERT INTO clinical_attachment_removal (clinic_id, attachment_id, reason, "
        "removed_by_user_id) VALUES (:c, :a, 'Motivo ficticio de baja', :u) RETURNING id",
        {**p, "a": ids["clinical_attachment"]},
    )
    ids["treatment_plan"] = await _sql(
        session,
        "INSERT INTO treatment_plan (clinic_id, record_id, title, created_by_user_id) "
        "VALUES (:c, :r, 'Plan ficticio', :u) RETURNING id",
        p,
    )
    ids["treatment_plan_version"] = await _sql(
        session,
        "INSERT INTO treatment_plan_version (clinic_id, plan_id, version, created_by_user_id) "
        "VALUES (:c, :plan, 1, :u) RETURNING id",
        {**p, "plan": ids["treatment_plan"]},
    )
    ids["treatment_plan_item"] = await _sql(
        session,
        "INSERT INTO treatment_plan_item (clinic_id, version_id, phase, position, description, "
        "quantity, unit_price_cents) VALUES (:c, :v, 1, 1, 'Item ficticio', 1, 100) RETURNING id",
        {**p, "v": ids["treatment_plan_version"]},
    )
    ids["treatment_plan_decision"] = await _sql(
        session,
        "INSERT INTO treatment_plan_decision (clinic_id, version_id, decision, "
        "decided_by_user_id) VALUES (:c, :v, 'accepted', :u) RETURNING id",
        {**p, "v": ids["treatment_plan_version"]},
    )
    ids["clinical_access_event"] = await _sql(
        session,
        "INSERT INTO clinical_access_event (clinic_id, record_id, actor_user_id, action) "
        "VALUES (:c, :r, :u, 'record_read') RETURNING id",
        p,
    )
    return ids


@pytest.mark.parametrize("tabla", CLINICAL_APPEND_ONLY)
async def test_el_trigger_rechaza_update_y_delete_del_dueno(
    db_session: AsyncSession, tabla: str
) -> None:
    ids = await _una_fila_por_tabla(db_session)

    for sentencia in (
        f"UPDATE {tabla} SET id = id WHERE id = :i",
        f"DELETE FROM {tabla} WHERE id = :i",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            async with db_session.begin_nested():
                await db_session.execute(text(sentencia), {"i": ids[tabla]})

    restantes = await _sql(
        db_session, f"SELECT count(*) FROM {tabla} WHERE id = :i", {"i": ids[tabla]}
    )
    assert restantes == 1


def test_las_tablas_clinicas_append_only_estan_en_el_contrato_de_privilegios() -> None:
    assert set(CLINICAL_APPEND_ONLY) <= set(APPEND_ONLY_TABLES)
    assert "odontogram_condition" not in APPEND_ONLY_TABLES


@pytest.mark.parametrize("tabla", CLINICAL_APPEND_ONLY)
async def test_app_writer_no_tiene_update_ni_delete(db_session: AsyncSession, tabla: str) -> None:
    privilegios = {
        priv: await _sql(
            db_session, f"SELECT has_table_privilege('{APP_ROLE}', '{tabla}', '{priv}')"
        )
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
    }

    assert privilegios == {
        "SELECT": True,
        "INSERT": True,
        "UPDATE": False,
        "DELETE": False,
        "TRUNCATE": False,
    }


async def test_el_catalogo_es_operativo_sin_delete(db_session: AsyncSession) -> None:
    """`odontogram_condition` se desactiva (UPDATE), nunca se borra."""
    assert await _sql(
        db_session, f"SELECT has_table_privilege('{APP_ROLE}', 'odontogram_condition', 'UPDATE')"
    )
    assert not await _sql(
        db_session, f"SELECT has_table_privilege('{APP_ROLE}', 'odontogram_condition', 'DELETE')"
    )
