"""Puerto de envío, render, ventana de Meta y selección de proveedores (C-09, D5/D10)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from app.core.settings import Settings
from app.models import ReminderChannel
from app.modules.reminders.senders import build_senders
from app.modules.reminders.senders.base import OutboundMessage, SendError
from app.modules.reminders.senders.fake import FakeSender
from app.modules.reminders.senders.render import MissingVariable, format_date, format_time, render
from app.modules.reminders.senders.smtp import SmtpSender
from app.modules.reminders.senders.window import choose_message_kind

BA = ZoneInfo("America/Argentina/Buenos_Aires")
TELEFONO = "+5491155550188"
EMAIL = "paciente.ficticio@example.com"
BASE = {
    "DATABASE_URL": "postgresql+asyncpg://turnos:clave@localhost:5432/turnos_test",
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_SECRET": "s" * 32,
}


def _settings(**cambios: object) -> Settings:
    return Settings.model_validate({**BASE, **cambios})


# ------------------------------------------------------------------ render


def test_la_hora_se_muestra_en_la_zona_de_la_clinica() -> None:
    inicio = datetime(2030, 1, 10, 18, 30, tzinfo=UTC)

    assert format_time(inicio, BA) == "15:30"


def test_la_fecha_es_argentina_con_dia_en_espanol_sin_depender_del_locale() -> None:
    # 2030-01-10 es jueves
    assert format_date(datetime(2030, 1, 10, 18, 30, tzinfo=UTC), BA) == "jueves 10/1"
    assert format_date(datetime(2030, 1, 14, 12, 0, tzinfo=UTC), BA) == "lunes 14/1"
    assert format_date(datetime(2030, 10, 9, 12, 0, tzinfo=UTC), BA) == "miércoles 9/10"


def test_la_fecha_usa_el_dia_local_no_el_utc() -> None:
    # 01:00 UTC del 11/1 es 22:00 del 10/1 en Buenos Aires
    assert format_date(datetime(2030, 1, 11, 1, 0, tzinfo=UTC), BA) == "jueves 10/1"


def test_render_reemplaza_las_variables() -> None:
    texto = render(
        "Hola {{nombre}}, tu turno es {{fecha}} a las {{hora}}",
        {
            "nombre": "María",
            "fecha": "jueves 10/1",
            "hora": "15:30",
            "sobrante": "x",
        },
    )

    assert texto == "Hola María, tu turno es jueves 10/1 a las 15:30"


def test_una_variable_faltante_falla_en_vez_de_enviar_la_llave_cruda() -> None:
    with pytest.raises(MissingVariable) as exc_info:
        render("Hola {{nombre}} {{link}}", {"nombre": "María"})

    assert "link" in str(exc_info.value)
    assert "María" not in str(exc_info.value)


# ------------------------------------------------------------- mensaje y errores


def _mensaje(canal: ReminderChannel = ReminderChannel.WHATSAPP) -> OutboundMessage:
    return OutboundMessage(
        channel=canal,
        to=TELEFONO if canal is ReminderChannel.WHATSAPP else EMAIL,
        template_name="recordatorio_24h_v1",
        locale="es_AR",
        params={"nombre": "María Ficticia", "link": "https://x.example.com/g/token-secreto"},
        body="Hola María Ficticia, https://x.example.com/g/token-secreto",
        subject="Tu turno",
    )


def test_el_mensaje_no_muestra_destinatario_ni_cuerpo_en_repr_ni_str() -> None:
    mensaje = _mensaje()

    for texto in (repr(mensaje), str(mensaje), f"{mensaje}", f"{[mensaje]}"):
        assert TELEFONO not in texto
        assert "María" not in texto
        assert "token-secreto" not in texto
    assert "recordatorio_24h_v1" in repr(mensaje)


def test_send_error_solo_expone_el_codigo() -> None:
    error = SendError("timeout", retryable=True)

    assert str(error) == "timeout"
    assert error.retryable is True and error.code == "timeout"


# ---------------------------------------------------------------- fake sender


async def test_el_fake_registra_los_envios_y_su_log_no_tiene_pii(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    sender = FakeSender(ReminderChannel.WHATSAPP)

    primero = await sender.send(_mensaje())
    segundo = await sender.send(_mensaje())

    assert [m.to for m in sender.sent] == [TELEFONO, TELEFONO]
    assert primero.provider_message_id != segundo.provider_message_id
    assert primero.provider_message_id.startswith("fake-")
    for registro in caplog.records:
        texto = registro.getMessage()
        assert TELEFONO not in texto and "María" not in texto and "token-secreto" not in texto


async def test_el_fake_puede_simular_fallos_en_orden() -> None:
    sender = FakeSender(ReminderChannel.EMAIL)
    sender.failures.extend(
        [SendError("timeout", retryable=True), SendError("rejected", retryable=False)]
    )

    with pytest.raises(SendError) as primero:
        await sender.send(_mensaje(ReminderChannel.EMAIL))
    with pytest.raises(SendError) as segundo:
        await sender.send(_mensaje(ReminderChannel.EMAIL))
    exito = await sender.send(_mensaje(ReminderChannel.EMAIL))

    assert (primero.value.retryable, segundo.value.retryable) == (True, False)
    assert exito.provider_message_id
    assert len(sender.sent) == 1


# ----------------------------------------------------------- ventana de Meta (RN-WA-03)


def test_sin_mensaje_entrante_el_recordatorio_es_plantilla() -> None:
    ahora = datetime(2030, 1, 7, 8, 0, tzinfo=UTC)

    assert choose_message_kind(None, ahora) == "template"


@pytest.mark.parametrize(
    ("hace", "esperado"),
    [
        (timedelta(hours=2), "session"),
        (timedelta(hours=23, minutes=59), "session"),
        (timedelta(hours=24), "template"),
        (timedelta(hours=25), "template"),
    ],
)
def test_dentro_de_las_24_horas_del_ultimo_entrante_habilita_el_seguimiento_libre(
    hace: timedelta, esperado: str
) -> None:
    ahora = datetime(2030, 1, 7, 8, 0, tzinfo=UTC)

    assert choose_message_kind(ahora - hace, ahora) == esperado


def test_un_entrante_futuro_no_abre_la_ventana() -> None:
    ahora = datetime(2030, 1, 7, 8, 0, tzinfo=UTC)

    assert choose_message_kind(ahora + timedelta(hours=1), ahora) == "template"


# --------------------------------------------------------------- proveedores


def test_por_defecto_ningun_canal_esta_habilitado() -> None:
    assert build_senders(_settings()) == {}


def test_los_proveedores_fake_habilitan_sus_canales() -> None:
    senders = build_senders(
        _settings(REMINDER_WHATSAPP_PROVIDER="fake", REMINDER_EMAIL_PROVIDER="fake")
    )

    assert set(senders) == {ReminderChannel.WHATSAPP, ReminderChannel.EMAIL}
    assert all(isinstance(s, FakeSender) for s in senders.values())
    assert senders[ReminderChannel.WHATSAPP].channel is ReminderChannel.WHATSAPP


def test_el_email_smtp_usa_el_adaptador_smtp() -> None:
    senders = build_senders(
        _settings(
            REMINDER_EMAIL_PROVIDER="smtp",
            EMAIL_HOST="smtp.example.com",
            EMAIL_FROM="turnos@example.com",
        )
    )

    assert set(senders) == {ReminderChannel.EMAIL}
    assert isinstance(senders[ReminderChannel.EMAIL], SmtpSender)


def test_smtp_sin_host_o_remitente_falla_al_armarse_y_sin_imprimir_credenciales() -> None:
    with pytest.raises(ValueError, match="EMAIL_HOST") as exc_info:
        build_senders(
            _settings(REMINDER_EMAIL_PROVIDER="smtp", EMAIL_PASSWORD="clave-secreta-ficticia")
        )

    assert "clave-secreta-ficticia" not in str(exc_info.value)
