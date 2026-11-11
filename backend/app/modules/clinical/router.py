"""Router clínico (C-15, D10). Todo bajo `/api`, todo `Cache-Control: no-store`.

Guardas (D4): lecturas con `ClinicalReader` (admin u odontólogo), escrituras con
`ClinicalWriter` (además `professional_id`), bitácora con `ClinicalAdmin`. Recepción recibe
`403 forbidden_role` en todas. El `no-store` lo fija `SecurityHeadersMiddleware` para toda
respuesta bajo los prefijos clínicos, también en los errores (`is_clinical_path`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Path, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.clock import get_now
from app.core.deps import get_db
from app.models import AttachmentKind, ClinicalAction
from app.modules.clinical.access import (
    ClinicalAdmin,
    ClinicalReader,
    ClinicalWriter,
    resolve_record,
)
from app.modules.clinical.attachments import AttachmentService, get_attachment_storage
from app.modules.clinical.audit import access_log_page, record_access
from app.modules.clinical.cursor import DEFAULT_LIMIT, MAX_LIMIT
from app.modules.clinical.evolutions import EvolutionService
from app.modules.clinical.odontogram import OdontogramService
from app.modules.clinical.plans import PlanService
from app.modules.clinical.schemas import (
    AccessLogPage,
    AnamnesisCreate,
    AnamnesisRead,
    AnamnesisVersionsPage,
    AttachmentRead,
    AttachmentsPage,
    ConditionsList,
    CorrectionCreate,
    DecisionCreate,
    DentitionName,
    EvolutionCreate,
    EvolutionRead,
    EvolutionsPage,
    OdontogramBatch,
    OdontogramEventsCreated,
    OdontogramRead,
    PlanCreate,
    PlanDetail,
    PlansPage,
    PlanVersionCreate,
    RecordOpened,
    RecordRead,
    RemovalCreate,
    RemovalRead,
    ToothHistoryPage,
)
from app.modules.clinical.service import AnamnesisService, RecordService
from app.modules.clinical.storage.base import AttachmentStorage

router = APIRouter(prefix="/api", tags=["clinical"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Cursor = Annotated[str | None, Query(max_length=200)]
Now = Annotated[datetime, Depends(get_now)]
Storage = Annotated[AttachmentStorage, Depends(get_attachment_storage)]


def _attachments(
    request: Request, session: AsyncSession, principal: object, storage: AttachmentStorage
) -> AttachmentService:
    maximo = int(request.app.state.settings.CLINICAL_MAX_ATTACHMENT_BYTES)
    return AttachmentService(session, principal, storage, maximo)  # type: ignore[arg-type]


def _disposition(nombre: str) -> str:
    prohibidos = {'"', "\\"}
    ascii_ = "".join(
        c if c.isascii() and c.isprintable() and c not in prohibidos else "_" for c in nombre
    )
    return f"attachment; filename=\"{ascii_}\"; filename*=UTF-8''{quote(nombre, safe='')}"


# ------------------------------------------------------------------ ficha


@router.post(
    "/patients/{patient_id}/clinical-record",
    response_model=RecordOpened,
    status_code=201,
    responses={200: {"model": RecordOpened}},
)
async def open_clinical_record(
    patient_id: uuid.UUID, principal: ClinicalWriter, session: DbSession, response: Response
) -> RecordOpened:
    """Abre la ficha (`201`) o devuelve la existente (`200`); archivado → `409`."""
    abierta = await RecordService(session, principal).open(patient_id)
    if not abierta.created:
        response.status_code = 200
    return abierta


@router.get("/patients/{patient_id}/clinical-record", response_model=RecordRead)
async def get_clinical_record(
    patient_id: uuid.UUID, principal: ClinicalReader, session: DbSession
) -> RecordRead:
    """Ficha con la anamnesis vigente y conteos; sin abrir → `404 clinical_record_not_opened`."""
    return await RecordService(session, principal).get(patient_id)


# ------------------------------------------------------------------ anamnesis


@router.post(
    "/clinical-records/{record_id}/anamnesis", response_model=AnamnesisRead, status_code=201
)
async def create_anamnesis(
    record_id: uuid.UUID, payload: AnamnesisCreate, principal: ClinicalWriter, session: DbSession
) -> AnamnesisRead:
    """Versión N+1; `expected_version` desactualizado → `409 version_conflict`."""
    return await AnamnesisService(session, principal).create(record_id, payload)


@router.get("/clinical-records/{record_id}/anamnesis", response_model=AnamnesisRead | None)
async def get_anamnesis(
    record_id: uuid.UUID, principal: ClinicalReader, session: DbSession
) -> AnamnesisRead | None:
    """Versión vigente (la mayor) o `null` si todavía no hay."""
    return await AnamnesisService(session, principal).current(record_id)


@router.get(
    "/clinical-records/{record_id}/anamnesis/versions", response_model=AnamnesisVersionsPage
)
async def list_anamnesis_versions(
    record_id: uuid.UUID,
    principal: ClinicalReader,
    session: DbSession,
    cursor: Annotated[int | None, Query(ge=2)] = None,
    limit: Limit = DEFAULT_LIMIT,
) -> AnamnesisVersionsPage:
    """Historial completo e inmutable, la más nueva primero."""
    return await AnamnesisService(session, principal).versions(record_id, cursor, limit)


# ------------------------------------------------------------------ odontograma


@router.get("/odontogram/conditions", response_model=ConditionsList)
async def list_odontogram_conditions(
    principal: ClinicalReader, session: DbSession
) -> ConditionsList:
    """Catálogo de estados de la clínica (solo lectura en C-15)."""
    return await OdontogramService(session, principal).conditions()


@router.post(
    "/clinical-records/{record_id}/odontogram/events",
    response_model=OdontogramEventsCreated,
    status_code=201,
)
async def record_odontogram_events(
    record_id: uuid.UUID, payload: OdontogramBatch, principal: ClinicalWriter, session: DbSession
) -> OdontogramEventsCreated:
    """Lote de 1 a 32 hallazgos en una transacción (todo o nada)."""
    return await OdontogramService(session, principal).record_events(record_id, payload)


@router.get("/clinical-records/{record_id}/odontogram", response_model=OdontogramRead)
async def get_odontogram(
    record_id: uuid.UUID,
    principal: ClinicalReader,
    session: DbSession,
    dentition: DentitionName = "permanent",
) -> OdontogramRead:
    """Estado vigente por pieza y cara, derivado del historial."""
    return await OdontogramService(session, principal).current(record_id, dentition)


@router.get(
    "/clinical-records/{record_id}/odontogram/teeth/{tooth}/history",
    response_model=ToothHistoryPage,
)
async def get_tooth_history(
    record_id: uuid.UUID,
    tooth: Annotated[int, Path()],
    principal: ClinicalReader,
    session: DbSession,
    cursor: Cursor = None,
    limit: Limit = DEFAULT_LIMIT,
) -> ToothHistoryPage:
    """Historial inmutable de una pieza, más reciente primero."""
    return await OdontogramService(session, principal).history(record_id, tooth, cursor, limit)


# ------------------------------------------------------------------ evoluciones


@router.post(
    "/clinical-records/{record_id}/evolutions", response_model=EvolutionRead, status_code=201
)
async def create_evolution(
    record_id: uuid.UUID,
    payload: EvolutionCreate,
    principal: ClinicalWriter,
    session: DbSession,
    now: Now,
) -> EvolutionRead:
    """Evolución firmada (firma simple: identidad + sello del servidor + SHA-256)."""
    return await EvolutionService(session, principal, now).create(record_id, payload)


@router.post(
    "/clinical-records/{record_id}/evolutions/{evolution_id}/corrections",
    response_model=EvolutionRead,
    status_code=201,
)
async def correct_evolution(
    record_id: uuid.UUID,
    evolution_id: uuid.UUID,
    payload: CorrectionCreate,
    principal: ClinicalWriter,
    session: DbSession,
    now: Now,
) -> EvolutionRead:
    """Corrección como entrada nueva (solo el autor); la original no cambia."""
    return await EvolutionService(session, principal, now).correct(record_id, evolution_id, payload)


@router.get("/clinical-records/{record_id}/evolutions", response_model=EvolutionsPage)
async def list_evolutions(
    record_id: uuid.UUID,
    principal: ClinicalReader,
    session: DbSession,
    now: Now,
    appointment_id: uuid.UUID | None = None,
    cursor: Cursor = None,
    limit: Limit = DEFAULT_LIMIT,
) -> EvolutionsPage:
    """Originales y correcciones, más recientes primero, con la marca `corrected_by`."""
    return await EvolutionService(session, principal, now).list(
        record_id, appointment_id, cursor, limit
    )


# ------------------------------------------------------------------ adjuntos


@router.post(
    "/clinical-records/{record_id}/attachments", response_model=AttachmentRead, status_code=201
)
async def upload_attachment(
    request: Request,
    record_id: uuid.UUID,
    principal: ClinicalWriter,
    session: DbSession,
    storage: Storage,
    file: Annotated[UploadFile, File()],
    kind: Annotated[AttachmentKind, Form()],
    evolution_id: Annotated[uuid.UUID | None, Form()] = None,
) -> AttachmentRead:
    """JPEG/PNG/PDF verificado por contenido, hasta el tope configurado (10 MiB)."""
    return await _attachments(request, session, principal, storage).upload(
        record_id, file, kind, evolution_id
    )


@router.get("/clinical-records/{record_id}/attachments", response_model=AttachmentsPage)
async def list_attachments(
    request: Request,
    record_id: uuid.UUID,
    principal: ClinicalReader,
    session: DbSession,
    storage: Storage,
    include_removed: bool = False,
    cursor: Cursor = None,
    limit: Limit = DEFAULT_LIMIT,
) -> AttachmentsPage:
    """Metadatos (nunca bytes ni `storage_key`); bajas solo para el admin."""
    return await _attachments(request, session, principal, storage).list(
        record_id, include_removed, cursor, limit
    )


@router.get("/clinical-records/{record_id}/attachments/{attachment_id}/content")
async def download_attachment(
    request: Request,
    record_id: uuid.UUID,
    attachment_id: uuid.UUID,
    principal: ClinicalReader,
    session: DbSession,
    storage: Storage,
) -> StreamingResponse:
    """Descarga autenticada: `attachment`, tipo verificado, `nosniff`, `no-store`."""
    descarga = await _attachments(request, session, principal, storage).download(
        record_id, attachment_id
    )
    return StreamingResponse(
        descarga.chunks,
        media_type=descarga.content_type,
        headers={
            "Content-Disposition": _disposition(descarga.display_name),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/clinical-records/{record_id}/attachments/{attachment_id}/removal",
    response_model=RemovalRead,
    status_code=201,
)
async def remove_attachment(
    request: Request,
    record_id: uuid.UUID,
    attachment_id: uuid.UUID,
    payload: RemovalCreate,
    principal: ClinicalWriter,
    session: DbSession,
    storage: Storage,
) -> RemovalRead:
    """Baja lógica con motivo; el archivo se conserva."""
    return await _attachments(request, session, principal, storage).remove(
        record_id, attachment_id, payload
    )


# ------------------------------------------------------------------ presupuestos

_PLANS = "/clinical-records/{record_id}/treatment-plans"


@router.post(_PLANS, response_model=PlanDetail, status_code=201)
async def create_plan(
    record_id: uuid.UUID, payload: PlanCreate, principal: ClinicalWriter, session: DbSession
) -> PlanDetail:
    """Plan con su versión 1; totales calculados por el servidor."""
    return await PlanService(session, principal).create(record_id, payload)


@router.get(_PLANS, response_model=PlansPage)
async def list_plans(
    record_id: uuid.UUID,
    principal: ClinicalReader,
    session: DbSession,
    cursor: Cursor = None,
    limit: Limit = DEFAULT_LIMIT,
) -> PlansPage:
    """Planes con su última versión, total y decisión vigente."""
    return await PlanService(session, principal).list(record_id, cursor, limit)


@router.get(_PLANS + "/{plan_id}", response_model=PlanDetail)
async def get_plan(
    record_id: uuid.UUID, plan_id: uuid.UUID, principal: ClinicalReader, session: DbSession
) -> PlanDetail:
    """Todas las versiones con sus decisiones."""
    return await PlanService(session, principal).get(record_id, plan_id)


@router.post(_PLANS + "/{plan_id}/versions", response_model=PlanDetail, status_code=201)
async def create_plan_version(
    record_id: uuid.UUID,
    plan_id: uuid.UUID,
    payload: PlanVersionCreate,
    principal: ClinicalWriter,
    session: DbSession,
) -> PlanDetail:
    """Versión N+1 con `expected_version`; la anterior queda intacta."""
    return await PlanService(session, principal).add_version(record_id, plan_id, payload)


@router.post(
    _PLANS + "/{plan_id}/versions/{version}/decision", response_model=PlanDetail, status_code=201
)
async def decide_plan_version(
    record_id: uuid.UUID,
    plan_id: uuid.UUID,
    version: Annotated[int, Path(ge=1)],
    payload: DecisionCreate,
    principal: ClinicalWriter,
    session: DbSession,
) -> PlanDetail:
    """Aceptado/rechazado sobre la última versión (una sola decisión por versión)."""
    return await PlanService(session, principal).decide(record_id, plan_id, version, payload)


@router.get(_PLANS + "/{plan_id}/versions/{version}/pdf")
async def export_plan_pdf(
    record_id: uuid.UUID,
    plan_id: uuid.UUID,
    version: Annotated[int, Path(ge=1)],
    principal: ClinicalReader,
    session: DbSession,
    now: Now,
) -> Response:
    """PDF al vuelo (no se persiste), sin DNI ni teléfono."""
    contenido = await PlanService(session, principal).pdf(record_id, plan_id, version, now)
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="presupuesto-v{version}.pdf"',
            "Cache-Control": "no-store",
        },
    )


# ------------------------------------------------------------------ bitácora


@router.get("/clinical-records/{record_id}/access-log", response_model=AccessLogPage)
async def get_access_log(
    record_id: uuid.UUID,
    principal: ClinicalAdmin,
    session: DbSession,
    cursor: Cursor = None,
    limit: Limit = DEFAULT_LIMIT,
) -> AccessLogPage:
    """Bitácora de accesos de la ficha, solo admin, más recientes primero."""
    ficha = await resolve_record(session, principal, record_id)
    pagina = await access_log_page(session, principal, ficha.id, cursor, limit)
    await record_access(session, principal, ficha.id, ClinicalAction.ACCESS_LOG_READ)
    await session.commit()
    return pagina
