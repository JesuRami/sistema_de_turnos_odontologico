"""Consentimiento por canal: único escritor de `consent` y de `patient.whatsapp_opt_in` (D8).

El estado vigente por paciente y canal es el de la última fila de `consent`; `whatsapp_opt_in`
es su proyección (el motor lee ese booleano ya cargado con el paciente). Ambos cambian juntos en
la transacción del llamador (sin commit): si esa transacción revierte, ninguno cambia. Ningún
otro módulo debe asignar `patient.whatsapp_opt_in`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Appointment,
    Consent,
    ConsentSource,
    ConsentStatus,
    Patient,
    ReminderChannel,
    ReminderJob,
    ReminderReason,
    ReminderStatus,
)
from app.modules.reminders.jobs import close_scheduled


class ConsentService:
    """Registra cambios de consentimiento y los hace efectivos sobre los jobs pendientes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def current(
        self, clinic_id: uuid.UUID, patient_id: uuid.UUID, channel: ReminderChannel
    ) -> ConsentStatus | None:
        """Estado de la última fila del canal, o `None` si el paciente nunca tuvo ninguna."""
        estado: ConsentStatus | None = await self.session.scalar(
            select(Consent.status)
            .where(
                Consent.clinic_id == clinic_id,
                Consent.patient_id == patient_id,
                Consent.channel == channel,
            )
            .order_by(Consent.changed_at.desc(), Consent.id)
            .limit(1)
        )
        return estado

    async def record(
        self,
        patient: Patient,
        channel: ReminderChannel,
        status: ConsentStatus,
        source: ConsentSource,
        *,
        user_id: uuid.UUID | None = None,
    ) -> bool:
        """Agrega el cambio si el estado vigente es otro; devuelve si hubo cambio.

        Una baja deja `skipped` (`no_consent`) los jobs `scheduled` de ese paciente y canal en
        la misma transacción; un alta posterior no los revive.
        """
        if source is ConsentSource.RECEPTION and user_id is None:
            raise ValueError("el consentimiento cargado por reception exige user_id")
        vigente = await self.current(patient.clinic_id, patient.id, channel)
        if vigente is status:
            return False
        self.session.add(
            Consent(
                clinic_id=patient.clinic_id,
                patient_id=patient.id,
                channel=channel,
                status=status,
                source=source,
                changed_by_user_id=user_id,
            )
        )
        if channel is ReminderChannel.WHATSAPP:
            patient.whatsapp_opt_in = status is ConsentStatus.OPT_IN
        await self.session.flush()
        if status is ConsentStatus.OPT_OUT:
            await close_scheduled(
                self.session,
                [
                    ReminderJob.clinic_id == patient.clinic_id,
                    ReminderJob.channel == channel,
                    ReminderJob.appointment_id.in_(
                        select(Appointment.id).where(
                            Appointment.clinic_id == patient.clinic_id,
                            Appointment.patient_id == patient.id,
                        )
                    ),
                ],
                to=ReminderStatus.SKIPPED,
                reason=ReminderReason.NO_CONSENT,
            )
        return True
