"""Migraciones c02→c04 contra Postgres 15 real (DB temporal propia por test)."""

from alembic import command

from tests.db_utils import alembic_config, fetch_rows

TABLAS = {
    "clinic",
    "professional",
    "chair",
    "schedule_rule",
    "patient",
    "user",
    "auth_event",
    "block",
    "agenda_config_event",
    "appointment",
    "appointment_event",
    "patient_merge",
    "notification_template",
    "reminder_job",
    "delivery_event",
    "consent",
}
INDICES = {
    "uq_clinic_slug",
    "ix_professional_clinic_id_active",
    "ix_chair_clinic_id_active",
    "ix_patient_clinic_id_phone_e164",
    "ix_patient_full_name_trgm",
    "ix_schedule_rule_professional_id_chair_id_weekday",
    "ix_auth_event_clinic_id_created_at",
    "ix_auth_event_user_id_created_at",
    "uq_user_clinic_id_id",
    "ex_schedule_rule_no_overlap",
    "ix_block_clinic_id_starts_at",
    "ix_agenda_config_event_clinic_id_created_at",
    "uq_patient_id_clinic_id",
    "uq_appointment_clinic_id_id",
    "ex_appointment_professional_no_overlap",
    "ex_appointment_chair_no_overlap",
    "ix_appointment_clinic_id_starts_at",
    "ix_appointment_professional_id_starts_at",
    "ix_appointment_patient_id_starts_at",
    "ix_appointment_event_appointment_id_created_at",
    "ix_appointment_event_clinic_id_created_at",
    "ix_patient_merge_clinic_id_created_at",
    "uq_notification_template_clinic_id_id",
    "uq_notification_template_clinic_id_channel_step",
    "uq_reminder_job_clinic_id_id",
    "uq_reminder_job_appointment_id_step_channel",
    "ix_reminder_job_due",
    "ix_reminder_job_claimed",
    "ix_reminder_job_clinic_step_sent",
    "ix_delivery_event_reminder_job_id_occurred_at",
    "uq_delivery_event_job_provider_event",
    "ix_consent_patient_channel_changed",
}
ENUMS = {
    "user_role",
    "auth_event_type",
    "block_reason",
    "config_entity",
    "config_action",
    "appointment_status",
    "appointment_origin",
    "cancellation_reason",
    "appointment_event_type",
    "actor_type",
    "reminder_channel",
    "reminder_status",
    "consent_status",
    "consent_source",
    "delivery_event_type",
}


def _tablas(url: str) -> set[str]:
    rows = fetch_rows(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
        "AND tablename <> 'alembic_version'",
        url,
    )
    return {str(r[0]) for r in rows}


def _indices(url: str) -> set[str]:
    return {str(r[0]) for r in fetch_rows("SELECT indexname FROM pg_indexes", url)}


def _enums(url: str) -> set[str]:
    return {str(r[0]) for r in fetch_rows("SELECT typname FROM pg_type WHERE typtype = 'e'", url)}


def _esquema(url: str) -> list[tuple[object, ...]]:
    return fetch_rows(
        "SELECT table_name, column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns WHERE table_schema = 'public' "
        "ORDER BY table_name, column_name",
        url,
    ) + fetch_rows(
        "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) "
        "FROM pg_constraint WHERE connamespace = 'public'::regnamespace ORDER BY 1, 2",
        url,
    )


def test_ciclo_upgrade_downgrade_upgrade(temp_database: str) -> None:
    """WHEN upgrade head, downgrade base y upgrade head THEN los tres pasos terminan sin error."""
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_esquema_final_identico_tras_el_ciclo(temp_database: str) -> None:
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    primero = _esquema(temp_database)
    command.downgrade(cfg, "c01_base")
    command.upgrade(cfg, "head")

    assert primero != []
    assert _esquema(temp_database) == primero


def test_upgrade_crea_tablas_e_indices_del_change(temp_database: str) -> None:
    command.upgrade(alembic_config(), "head")

    assert _tablas(temp_database) == TABLAS
    assert INDICES <= _indices(temp_database)
    assert _enums(temp_database) == ENUMS


def test_upgrade_crea_los_objetos_de_auth_de_c03(temp_database: str) -> None:
    """WHEN upgrade head THEN existen password_changed_at, auth_event, enum, índices y trigger."""
    command.upgrade(alembic_config(), "head")

    columnas_user = {
        str(r[0])
        for r in fetch_rows(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'user'",
            temp_database,
        )
    }
    assert "password_changed_at" in columnas_user
    assert "auth_event" in _tablas(temp_database)
    assert "auth_event_type" in _enums(temp_database)
    assert {
        "ix_auth_event_clinic_id_created_at",
        "ix_auth_event_user_id_created_at",
    } <= _indices(temp_database)
    triggers = fetch_rows(
        "SELECT tgname FROM pg_trigger WHERE tgrelid = 'auth_event'::regclass "
        "AND NOT tgisinternal",
        temp_database,
    )
    assert {str(r[0]) for r in triggers} == {"trg_auth_event_no_mutate"}


def test_upgrade_crea_los_objetos_de_agenda_de_c04(temp_database: str) -> None:
    """WHEN upgrade head THEN existen EXCLUDE, columnas de política, block y su auditoría."""
    command.upgrade(alembic_config(), "head")

    exclude = fetch_rows(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname = 'ex_schedule_rule_no_overlap'",
        temp_database,
    )
    assert len(exclude) == 1
    assert "EXCLUDE USING gist" in str(exclude[0][0])
    assert "WHERE (active)" in str(exclude[0][0])
    columnas_clinic = {
        str(r[0])
        for r in fetch_rows(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'clinic'",
            temp_database,
        )
    }
    assert {"max_overbookings_per_day", "waitlist_offer_ttl_hours"} <= columnas_clinic
    no_validados = fetch_rows(
        "SELECT conname FROM pg_constraint WHERE conrelid = 'clinic'::regclass "
        "AND NOT convalidated",
        temp_database,
    )
    assert no_validados == []
    triggers = fetch_rows(
        "SELECT tgname FROM pg_trigger WHERE tgrelid = 'agenda_config_event'::regclass "
        "AND NOT tgisinternal",
        temp_database,
    )
    assert {str(r[0]) for r in triggers} == {"trg_agenda_config_event_no_mutate"}


def test_upgrade_crea_los_objetos_de_turnos_de_c05(temp_database: str) -> None:
    """WHEN upgrade head THEN existen los dos EXCLUDE con predicado de vigencia y el trigger."""
    command.upgrade(alembic_config(), "head")

    excludes = {
        str(r[0]): str(r[1])
        for r in fetch_rows(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'appointment'::regclass AND contype = 'x'",
            temp_database,
        )
    }
    assert set(excludes) == {
        "ex_appointment_professional_no_overlap",
        "ex_appointment_chair_no_overlap",
    }
    for definicion in excludes.values():
        assert "EXCLUDE USING gist" in definicion
        assert "tstzrange(starts_at, occupied_until, '[)'::text) WITH &&" in definicion
        assert "NOT is_overbooking" in definicion
        assert "'absent'" not in definicion
    triggers = fetch_rows(
        "SELECT tgname FROM pg_trigger WHERE tgrelid = 'appointment_event'::regclass "
        "AND NOT tgisinternal",
        temp_database,
    )
    assert {str(r[0]) for r in triggers} == {"trg_appointment_event_no_mutate"}
    no_validados = fetch_rows(
        "SELECT conname FROM pg_constraint WHERE connamespace = 'public'::regnamespace "
        "AND NOT convalidated",
        temp_database,
    )
    assert no_validados == []


def test_upgrade_crea_los_objetos_de_fusion_de_c06(temp_database: str) -> None:
    """WHEN upgrade head THEN existen el puntero validado, la FK compuesta y el trigger."""
    command.upgrade(alembic_config(), "head")

    columnas = {
        str(r[0])
        for r in fetch_rows(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'patient'",
            temp_database,
        )
    }
    assert "merged_into_patient_id" in columnas
    constraints = {
        str(r[0]): bool(r[1])
        for r in fetch_rows(
            "SELECT conname, convalidated FROM pg_constraint "
            "WHERE conrelid = 'patient'::regclass",
            temp_database,
        )
    }
    for nombre in (
        "fk_patient_merged_into_patient_id_clinic_id_patient",
        "ck_patient_not_merged_into_self",
        "ck_patient_merged_is_archived",
    ):
        assert constraints[nombre] is True, nombre
    triggers = fetch_rows(
        "SELECT tgname FROM pg_trigger WHERE tgrelid = 'patient_merge'::regclass "
        "AND NOT tgisinternal",
        temp_database,
    )
    assert {str(r[0]) for r in triggers} == {"trg_patient_merge_no_mutate"}


def test_downgrade_a_c05_elimina_los_objetos_de_c06(temp_database: str) -> None:
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "c05_appointments_core")

    assert "patient_merge" not in _tablas(temp_database)
    columnas = {
        str(r[0])
        for r in fetch_rows(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'patient'",
            temp_database,
        )
    }
    assert "merged_into_patient_id" not in columnas
    assert (
        fetch_rows(
            "SELECT proname FROM pg_proc WHERE proname = 'patient_merge_immutable'", temp_database
        )
        == []
    )


def test_downgrade_a_c04_elimina_los_objetos_de_c05(temp_database: str) -> None:
    """WHEN downgrade c04_agenda_config THEN no queda ningún objeto de c05."""
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "c04_agenda_config")

    assert {"appointment", "appointment_event"}.isdisjoint(_tablas(temp_database))
    assert {
        "appointment_status",
        "appointment_origin",
        "cancellation_reason",
        "appointment_event_type",
        "actor_type",
    }.isdisjoint(_enums(temp_database))
    assert "uq_patient_id_clinic_id" not in _indices(temp_database)
    funciones = fetch_rows(
        "SELECT proname FROM pg_proc WHERE proname = 'appointment_event_immutable'",
        temp_database,
    )
    assert funciones == []


def test_downgrade_a_c03_elimina_los_objetos_de_c04(temp_database: str) -> None:
    """WHEN downgrade c03_auth_rbac THEN no queda ningún objeto de c04."""
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "c03_auth_rbac")

    assert {"block", "agenda_config_event"}.isdisjoint(_tablas(temp_database))
    assert {"block_reason", "config_entity", "config_action"}.isdisjoint(_enums(temp_database))
    assert "ex_schedule_rule_no_overlap" not in _indices(temp_database)
    columnas_clinic = {
        str(r[0])
        for r in fetch_rows(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'clinic'",
            temp_database,
        )
    }
    assert {"max_overbookings_per_day", "waitlist_offer_ttl_hours"}.isdisjoint(columnas_clinic)


def test_downgrade_a_c02_elimina_los_objetos_de_c03(temp_database: str) -> None:
    """WHEN downgrade c02_core_models THEN no queda ningún objeto de c03."""
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "c02_core_models")

    assert "auth_event" not in _tablas(temp_database)
    assert "auth_event_type" not in _enums(temp_database)
    columnas_user = {
        str(r[0])
        for r in fetch_rows(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'user'",
            temp_database,
        )
    }
    assert "password_changed_at" not in columnas_user
    assert {
        "ix_auth_event_clinic_id_created_at",
        "ix_auth_event_user_id_created_at",
        "uq_user_clinic_id_id",
    }.isdisjoint(_indices(temp_database))


def test_indice_trigram_es_gin_con_gin_trgm_ops(temp_database: str) -> None:
    command.upgrade(alembic_config(), "head")

    definicion = fetch_rows(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_patient_full_name_trgm'",
        temp_database,
    )[0][0]
    assert "USING gin" in str(definicion)
    assert "gin_trgm_ops" in str(definicion)


def test_downgrade_no_deja_tablas_ni_enums_del_change(temp_database: str) -> None:
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "c01_base")

    assert _tablas(temp_database) == set()
    assert _enums(temp_database) == set()
    # pg_trgm puede quedar instalada (decisión de diseño 5.i).


def test_modelos_y_migracion_no_divergen(temp_database: str) -> None:
    """Autogenerate contra la DB migrada no debe proponer cambios (drift modelo↔migración)."""
    import asyncio
    import os

    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.core.database import async_database_url
    from app.models import Base
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    command.upgrade(alembic_config(), "head")

    async def _diff() -> list[object]:
        engine = create_async_engine(
            async_database_url(os.environ["DATABASE_URL"]), poolclass=NullPool
        )
        try:
            async with engine.connect() as conn:

                def _compare(sync_conn: object) -> list[object]:
                    ctx = MigrationContext.configure(sync_conn)  # type: ignore[arg-type]
                    return list(compare_metadata(ctx, Base.metadata))

                return await conn.run_sync(_compare)
        finally:
            await engine.dispose()

    assert asyncio.run(_diff()) == []


def test_cli_alembic_desde_la_raiz_del_repo(temp_database: str) -> None:
    """El CLI real (como en CI) resuelve `app` y migra: upgrade, downgrade -1, upgrade."""
    import os
    import subprocess
    import sys

    from tests.db_utils import ROOT

    env = {**os.environ, "DATABASE_URL": temp_database}
    for args in (["upgrade", "head"], ["downgrade", "-1"], ["upgrade", "head"]):
        resultado = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert resultado.returncode == 0, resultado.stderr
    assert _tablas(temp_database) == TABLAS


def test_upgrade_crea_la_instantanea_de_eventos_de_c13(temp_database: str) -> None:
    """WHEN upgrade head THEN existen columnas, FKs validadas, índice válido y el enum."""
    command.upgrade(alembic_config(), "head")

    columnas = {
        str(r[0])
        for r in fetch_rows(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'appointment_event'",
            temp_database,
        )
    }
    assert {"slot_starts_at", "slot_ends_at", "professional_id", "chair_id"} <= columnas
    indice = fetch_rows(
        "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        "WHERE c.relname = 'ix_appointment_event_clinic_id_slot_starts_at'",
        temp_database,
    )
    assert [bool(r[0]) for r in indice] == [True]
    restricciones = {
        str(r[0])
        for r in fetch_rows(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'appointment_event'::regclass "
            "AND convalidated",
            temp_database,
        )
    }
    assert {
        "fk_appointment_event_clinic_id_professional_id_professional",
        "fk_appointment_event_clinic_id_chair_id_chair",
        "ck_appointment_event_slot_coherent",
    } <= restricciones
    etiquetas = {
        str(r[0])
        for r in fetch_rows(
            "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = 'auth_event_type'",
            temp_database,
        )
    }
    assert "data_exported" in etiquetas
    triggers = fetch_rows(
        "SELECT tgname FROM pg_trigger WHERE tgrelid = 'appointment_event'::regclass "
        "AND NOT tgisinternal",
        temp_database,
    )
    assert {str(r[0]) for r in triggers} == {"trg_appointment_event_no_mutate"}


def test_downgrade_a_c06_quita_la_instantanea_y_permite_volver_a_subir(temp_database: str) -> None:
    """WHEN downgrade c06 THEN no quedan columnas ni índice, y un nuevo upgrade funciona."""
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "c06_patient_merge")

    columnas = {
        str(r[0])
        for r in fetch_rows(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'appointment_event'",
            temp_database,
        )
    }
    assert columnas.isdisjoint({"slot_starts_at", "slot_ends_at", "professional_id", "chair_id"})
    assert (
        fetch_rows(
            "SELECT 1 FROM pg_class "
            "WHERE relname = 'ix_appointment_event_clinic_id_slot_starts_at'",
            temp_database,
        )
        == []
    )
    command.upgrade(cfg, "head")


# ------------------------------------------------------------------ C-09 motor-recordatorios


def _ejecutar(url: str, *sentencias: tuple[str, tuple[object, ...]]) -> None:
    """Ejecuta sentencias de escritura (con parámetros) contra la DB indicada."""
    import asyncio

    import asyncpg
    from sqlalchemy.engine import make_url

    async def _run() -> None:
        u = make_url(url)
        conn = await asyncpg.connect(
            user=u.username, password=u.password, host=u.host, port=u.port, database=u.database
        )
        try:
            for sql, args in sentencias:
                await conn.execute(sql, *args)
        finally:
            await conn.close()

    asyncio.run(_run())


def test_upgrade_crea_los_objetos_del_motor_de_recordatorios_de_c09(temp_database: str) -> None:
    """WHEN upgrade head THEN existen las cuatro tablas, los índices parciales y los triggers."""
    command.upgrade(alembic_config(), "head")

    assert {"notification_template", "reminder_job", "delivery_event", "consent"} <= _tablas(
        temp_database
    )
    triggers = fetch_rows(
        "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
        "AND tgname IN ('trg_delivery_event_no_mutate', 'trg_consent_no_mutate')",
        temp_database,
    )
    assert {str(r[0]) for r in triggers} == {
        "trg_delivery_event_no_mutate",
        "trg_consent_no_mutate",
    }
    cola = fetch_rows(
        "SELECT pg_get_indexdef(indexrelid) FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indexrelid "
        "WHERE c.relname = 'ix_reminder_job_due'",
        temp_database,
    )
    assert "WHERE (status = 'scheduled'" in str(cola[0][0])


def test_downgrade_a_c08_elimina_los_objetos_de_c09_y_conserva_el_flag(
    temp_database: str,
) -> None:
    cfg = alembic_config()
    command.upgrade(cfg, "c08_manage_token")
    _ejecutar(
        temp_database,
        ("INSERT INTO clinic (name, slug) VALUES ('Clínica Ficticia', 'clinica-c09-down')", ()),
        (
            "INSERT INTO patient (clinic_id, full_name, phone_e164, whatsapp_opt_in) "
            "SELECT id, 'Paciente Ficticio', '+5491155550101', true FROM clinic",
            (),
        ),
    )
    command.upgrade(cfg, "head")

    command.downgrade(cfg, "c08_manage_token")

    assert not {"notification_template", "reminder_job", "delivery_event", "consent"} & _tablas(
        temp_database
    )
    assert not {
        "reminder_channel",
        "reminder_status",
        "consent_status",
        "consent_source",
        "delivery_event_type",
    } & _enums(temp_database)
    assert fetch_rows("SELECT whatsapp_opt_in FROM patient", temp_database) == [(True,)]
    command.upgrade(cfg, "head")


def test_backfill_de_c09_registra_el_consentimiento_legacy_y_las_plantillas(
    temp_database: str,
) -> None:
    """Sobre una base en c08 con 2 clínicas y 2 pacientes, `upgrade head` siembra lo previo."""
    from app.modules.reminders.templates import DEFAULT_TEMPLATES

    cfg = alembic_config()
    command.upgrade(cfg, "c08_manage_token")
    _ejecutar(
        temp_database,
        ("INSERT INTO clinic (name, slug) VALUES ('Clínica Ficticia A', 'clinica-c09-a')", ()),
        ("INSERT INTO clinic (name, slug) VALUES ('Clínica Ficticia B', 'clinica-c09-b')", ()),
        (
            "INSERT INTO patient (clinic_id, full_name, phone_e164, whatsapp_opt_in) "
            "SELECT id, 'Paciente Ficticio Con Opt-in', '+5491155550102', true FROM clinic "
            "WHERE slug = 'clinica-c09-a'",
            (),
        ),
        (
            "INSERT INTO patient (clinic_id, full_name, phone_e164, whatsapp_opt_in) "
            "SELECT id, 'Paciente Ficticio Sin Opt-in', '+5491155550103', false FROM clinic "
            "WHERE slug = 'clinica-c09-a'",
            (),
        ),
    )

    command.upgrade(cfg, "head")

    consentimientos = fetch_rows(
        "SELECT p.full_name, c.channel::text, c.status::text, c.source::text "
        "FROM consent c JOIN patient p ON p.id = c.patient_id",
        temp_database,
    )
    assert consentimientos == [
        ("Paciente Ficticio Con Opt-in", "whatsapp", "opt_in", "legacy"),
    ]
    flags = {
        str(r[0]): r[1]
        for r in fetch_rows("SELECT full_name, whatsapp_opt_in FROM patient", temp_database)
    }
    assert flags == {
        "Paciente Ficticio Con Opt-in": True,
        "Paciente Ficticio Sin Opt-in": False,
    }
    por_clinica = fetch_rows(
        "SELECT count(*) FROM notification_template GROUP BY clinic_id", temp_database
    )
    assert sorted(por_clinica) == [(len(DEFAULT_TEMPLATES),), (len(DEFAULT_TEMPLATES),)]
    assert len(DEFAULT_TEMPLATES) == 8
