/**
 * Seguimiento de ofertas (C-12; spec web/waiting-list): pendientes con su cuenta regresiva y
 * acciones en nombre del paciente, y las vencidas, rechazadas y cerradas de hoy.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../shared/api/client";
import { messageFor } from "../../shared/api/errors";
import { useProfessionals } from "../../shared/api/queries";
import type { AcceptedOffer, WaitlistOffer, WaitlistOfferStatus } from "../../shared/api/types";
import { useClock } from "../../shared/time/now";
import { dateKeyOf } from "../../shared/time/zoned";
import { Alert, Button } from "../../shared/ui";
import { acceptOffer, cancelOffer, declineOffer, useOffers, waitlistKeys } from "./api";
import { remaining, slotLabel } from "./format";

const ESTADOS: readonly WaitlistOfferStatus[] = ["pending", "expired", "declined", "cancelled"];
const CERRADA: Record<WaitlistOfferStatus, string> = {
  pending: "Pendiente",
  accepted: "Aceptada",
  declined: "Rechazada",
  expired: "Vencida",
  cancelled: "Cerrada"
};

interface OffersPanelProps {
  timezone: string;
  /** Nombre del paciente por id de entrada (de la cola ya cargada). */
  patientOf: (entryId: string) => string | undefined;
}

type Resultado =
  | { tipo: "aceptada"; data: AcceptedOffer }
  | { tipo: "perdida" }
  | { tipo: "error"; error: unknown };

function OffersPanel({ timezone, patientOf }: OffersPanelProps): JSX.Element {
  const clock = useClock();
  const queryClient = useQueryClient();
  const ofertas = useOffers(ESTADOS, true);
  const profesionales = useProfessionals();
  const nombres = useMemo(
    () => new Map((profesionales.data ?? []).map((p) => [p.id, p.display_name])),
    [profesionales.data]
  );
  const [enCurso, setEnCurso] = useState<string | null>(null);
  const [resultado, setResultado] = useState<Resultado | null>(null);
  const ahora = clock();
  const hoy = dateKeyOf(ahora, timezone);

  async function actuar(
    oferta: WaitlistOffer,
    accion: (id: string) => Promise<unknown>,
    aceptar = false
  ): Promise<void> {
    setEnCurso(oferta.id);
    setResultado(null);
    try {
      const respuesta = await accion(oferta.id);
      if (aceptar) {
        setResultado({ tipo: "aceptada", data: respuesta as AcceptedOffer });
      }
    } catch (fallo) {
      setResultado(
        fallo instanceof ApiError && fallo.detail === "slot_taken"
          ? { tipo: "perdida" }
          : { tipo: "error", error: fallo }
      );
    } finally {
      setEnCurso(null);
      await queryClient.invalidateQueries({ queryKey: waitlistKeys.all });
    }
  }

  const todas = ofertas.data ?? [];
  const pendientes = todas.filter(
    (o) => o.status === "pending" && new Date(o.expires_at) > ahora
  );
  const cerradasHoy = todas.filter(
    (o) =>
      !pendientes.includes(o) && dateKeyOf(new Date(o.responded_at ?? o.expires_at), timezone) === hoy
  );

  function fila(o: WaitlistOffer): JSX.Element {
    return (
      <>
        <span className="font-medium">{patientOf(o.entry_id) ?? "Paciente"}</span>
        {" · "}
        {slotLabel(o.starts_at, timezone)} · {nombres.get(o.professional_id) ?? "Profesional"}
        {o.mode === "manual" ? " · manual" : ""}
      </>
    );
  }

  return (
    <section aria-labelledby="ofertas-titulo" className="mb-6 rounded-lg border border-dental-600/20 bg-white p-4">
      <h2 id="ofertas-titulo" className="text-lg font-semibold">
        Ofertas
      </h2>
      {ofertas.isError && <Alert>{messageFor(ofertas.error)}</Alert>}
      {resultado?.tipo === "aceptada" && (
        <Alert tone="success">
          Turno creado: {slotLabel(resultado.data.starts_at, timezone)}.{" "}
          <Link className="underline" to="/">
            Ver en la agenda
          </Link>
        </Alert>
      )}
      {resultado?.tipo === "perdida" && (
        <Alert>
          El hueco ya se ocupó. La entrada volvió a la cola como prioritaria para el próximo hueco.
        </Alert>
      )}
      {resultado?.tipo === "error" && <Alert>{messageFor(resultado.error)}</Alert>}
      <h3 className="mt-3 text-sm font-semibold">Pendientes ({pendientes.length})</h3>
      {pendientes.length === 0 && <p className="text-sm opacity-80">No hay ofertas pendientes.</p>}
      <ul className="mt-1 space-y-2">
        {pendientes.map((o) => (
          <li key={o.id} className="flex flex-wrap items-center gap-2 text-sm">
            <span>{fila(o)}</span>
            <span className="rounded bg-amber-100 px-1.5 text-xs">{remaining(o.expires_at, ahora)}</span>
            <Button
              disabled={enCurso === o.id}
              aria-label={`Aceptar por teléfono la oferta de ${patientOf(o.entry_id) ?? "paciente"}`}
              onClick={() => void actuar(o, acceptOffer, true)}
            >
              Aceptar
            </Button>
            <Button
              variant="secondary"
              disabled={enCurso === o.id}
              onClick={() => void actuar(o, declineOffer)}
            >
              Rechazar
            </Button>
            <Button
              variant="ghost"
              disabled={enCurso === o.id}
              onClick={() => void actuar(o, cancelOffer)}
            >
              Retirar
            </Button>
          </li>
        ))}
      </ul>
      <h3 className="mt-4 text-sm font-semibold">Cerradas hoy ({cerradasHoy.length})</h3>
      <ul className="mt-1 space-y-1">
        {cerradasHoy.map((o) => (
          <li key={o.id} className="text-sm">
            {fila(o)} — {o.status === "pending" ? "Vencida" : CERRADA[o.status]}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default OffersPanel;
