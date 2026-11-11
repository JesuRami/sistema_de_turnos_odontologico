"""PDF de presupuesto (C-15, D8, Decisión 6): `reportlab`, generado al vuelo y nunca persistido.

Lleva clínica, paciente (solo el nombre: sin DNI ni teléfono), fases, ítems, subtotales, total y
fecha de emisión en la zona de la clínica. No indica vigencia ni descuentos; no es una factura.
La fuente es Bitstream Vera (TTF que trae el paquete `reportlab`, pineado), embebida para acentos y
Ñ. Se llama desde un thread (`asyncio.to_thread`): no bloquea el loop.
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import reportlab
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.modules.clinical.schemas import PlanVersionRead

FONT = "ClinicalVera"
FONT_BOLD = "ClinicalVeraBold"
_FONTS_DIR = Path(reportlab.__file__).parent / "fonts"


def _register_fonts() -> None:
    registradas = pdfmetrics.getRegisteredFontNames()
    if FONT not in registradas:
        pdfmetrics.registerFont(TTFont(FONT, str(_FONTS_DIR / "Vera.ttf")))
    if FONT_BOLD not in registradas:
        pdfmetrics.registerFont(TTFont(FONT_BOLD, str(_FONTS_DIR / "VeraBd.ttf")))


def _ars(centavos: int) -> str:
    from app.modules.clinical.plans import format_ars

    return f"$ {format_ars(centavos)}"


def render_plan_pdf(
    *,
    clinic_name: str,
    patient_name: str,
    title: str,
    version: PlanVersionRead,
    issued_on: date,
) -> bytes:
    _register_fonts()
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4, pageCompression=0)
    pdf.setTitle("Presupuesto")
    ancho, alto = A4
    y = alto - 20 * mm

    def linea(texto: str, *, size: int = 10, bold: bool = False, x: float = 20 * mm) -> None:
        nonlocal y
        if y < 20 * mm:
            pdf.showPage()
            y = alto - 20 * mm
        pdf.setFont(FONT_BOLD if bold else FONT, size)
        pdf.drawString(x, y, texto)
        y -= size * 0.5 * mm + 3 * mm

    linea(clinic_name, size=14, bold=True)
    linea(f"Presupuesto: {title} (versión {version.version})", size=12, bold=True)
    linea(f"Paciente: {patient_name}")
    linea(f"Fecha de emisión: {issued_on.strftime('%d/%m/%Y')}")
    y -= 3 * mm
    for fase in version.phases:
        linea(f"Fase {fase.phase}", size=11, bold=True)
        for item in fase.items:
            pieza = f" — pieza {item.tooth}{item.surface or ''}" if item.tooth else ""
            linea(
                f"{item.quantity} × {item.description}{pieza}: "
                f"{_ars(item.unit_price_cents)} c/u = {_ars(item.subtotal_cents)}",
                x=25 * mm,
            )
        linea(f"Subtotal fase {fase.phase}: {_ars(fase.subtotal_cents)}", bold=True, x=25 * mm)
    y -= 3 * mm
    linea(f"Total: {_ars(version.total_cents)}", size=12, bold=True)
    linea("Documento informativo: no es una factura.", size=8)
    pdf.showPage()
    pdf.save()
    _ = ancho
    return buffer.getvalue()
