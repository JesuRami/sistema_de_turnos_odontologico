/**
 * Lista de espera para el personal (C-12; spec web/waiting-list): cola por prioridad y antigüedad
 * con filtros y "Cargar más", alta/edición/retiro, prioridad con motivo, oferta manual y el
 * seguimiento de ofertas. El odontólogo solo lee la cola de su profesional, sin contacto ni
 * acciones. Se refresca cada 30 s mientras la pestaña está visible.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { messageFor } from "../../shared/api/errors";
import { useClinic, useProfessionals } from "../../shared/api/queries";
import type { WaitingListEntry, WaitingListStatus } from "../../shared/api/types";
import { useAuth } from "../../shared/auth/AuthProvider";
import { useClock } from "../../shared/time/now";
import { dateKeyOf } from "../../shared/time/zoned";
import { Alert, Button, Modal, PageTitle, SelectField, TextArea, TextField } from "../../shared/ui";
import { Skeleton } from "../../shared/ui/Skeleton";
import {
  prioritizeEntry,
  unprioritizeEntry,
  useQueue,
  waitlistKeys,
  withdrawEntry,
  type QueueFilters
} from "./api";
import EntryForm from "./EntryForm";
import { periodLabel, remaining, slotLabel, windowLabel } from "./format";
import OfferDialog from "./OfferDialog";
import OffersPanel from "./OffersPanel";

const ESTADOS: Record<string, WaitingListStatus[]> = {
  activas: ["waiting", "offered"],
  converted: ["converted"],
  expired: ["expired"],
  withdrawn: ["withdrawn"]
};

type Dialogo =
  | { tipo: "alta" }
  | { tipo: "editar"; entry: WaitingListEntry }
  | { tipo: "ofrecer"; entry: WaitingListEntry }
  | { tipo: "prioridad"; entry: WaitingListEntry }
  | { tipo: "retirar"; entry: WaitingListEntry };

function WaitingListPage(): JSX.Element {
  const { user } = useAuth();
  const operador = user?.role === "admin" || user?.role === "recepcion";
  const clock = useClock();
  const queryClient = useQueryClient();
  const clinic = useClinic();
  const tz = clinic.data?.timezone ?? "America/Argentina/Buenos_Aires";
  const profesionales = useProfessionals();
  const nombres = useMemo(
    () => new Map((profesionales.data ?? []).map((p) => [p.id, p.display_name])),
    [profesionales.data]
  );
  const [estado, setEstado] = useState("activas");
  const [professionalId, setProfessionalId] = useState("");
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");
  const filtros: QueueFilters = {
    status: ESTADOS[estado] ?? ["waiting", "offered"],
    professionalId: professionalId === "" ? null : professionalId,
    from: desde === "" ? null : desde,
    to: hasta === "" ? null : hasta
  };
  const cola = useQueue(filtros);
  const [dialogo, setDialogo] = useState<Dialogo | null>(null);
  const [resaltada, setResaltada] = useState<string | null>(null);
  const [motivo, setMotivo] = useState("");
  const [errorAccion, setErrorAccion] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const ahora = clock();
  const hoy = dateKeyOf(ahora, tz);

  const entradas = useMemo(() => (cola.data?.pages ?? []).flatMap((p) => p.items), [cola.data]);
  const pacientePorEntrada = useMemo(
    () => new Map(entradas.map((e) => [e.id, e.patient.full_name])),
    [entradas]
  );

  async function ejecutar(accion: () => Promise<unknown>): Promise<void> {
    setPending(true);
    setErrorAccion(null);
    try {
      await accion();
      await queryClient.invalidateQueries({ queryKey: waitlistKeys.all });
      setDialogo(null);
      setMotivo("");
    } catch (fallo) {
      setErrorAccion(fallo);
    } finally {
      setPending(false);
    }
  }

  function cerrar(): void {
    setDialogo(null);
    setMotivo("");
    setErrorAccion(null);
  }

  return (
    <div>
      <PageTitle actions={operador ? <Button onClick={() => setDialogo({ tipo: "alta" })}>Anotar paciente</Button> : undefined}>
        Lista de espera
      </PageTitle>

      {operador && <OffersPanel timezone={tz} patientOf={(id) => pacientePorEntrada.get(id)} />}

      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4" role="group" aria-label="Filtros">
        <SelectField label="Estado" value={estado} onChange={(e) => setEstado(e.target.value)}>
          <option value="activas">En espera y ofrecidas</option>
          <option value="converted">Convertidas</option>
          <option value="expired">Vencidas</option>
          <option value="withdrawn">Retiradas</option>
        </SelectField>
        <SelectField
          label="Profesional"
          value={professionalId}
          onChange={(e) => setProfessionalId(e.target.value)}
        >
          <option value="">Todos</option>
          {(profesionales.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.display_name}
            </option>
          ))}
        </SelectField>
        <TextField label="Período desde" type="date" value={desde} onChange={(e) => setDesde(e.target.value)} />
        <TextField label="Período hasta" type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} />
      </div>

      {cola.isPending && <Skeleton label="Cargando la cola…" rows={4} />}
      {cola.isError && (
        <Alert>
          {messageFor(cola.error)}{" "}
          <Button variant="secondary" onClick={() => void cola.refetch()}>
            Reintentar
          </Button>
        </Alert>
      )}
      {cola.isSuccess && entradas.length === 0 && (
        <p className="text-sm">
          No hay pacientes en la lista con estos filtros.
          {operador ? " Usá “Anotar paciente” para sumar a alguien." : ""}
        </p>
      )}

      <ol className="space-y-2" aria-label="Cola">
        {entradas.map((e) => (
          <li
            key={e.id}
            className={`rounded-lg border bg-white p-3 text-sm ${resaltada === e.id ? "border-dental-600 ring-2 ring-dental-600" : "border-dental-600/20"}`}
          >
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="font-semibold">{e.patient.full_name}</span>
              {e.prioritized_at !== null && (
                <span className="rounded bg-rose-100 px-1.5 text-xs text-rose-900">
                  Prioritaria{e.priority_reason !== null ? `: ${e.priority_reason === "slot_lost" ? "perdió un hueco" : e.priority_reason}` : ""}
                </span>
              )}
              <span className="opacity-80">
                {e.professional_id === null ? "Cualquiera" : (nombres.get(e.professional_id) ?? "Profesional")}
              </span>
              <span>{periodLabel(e)}</span>
              <span className="opacity-80">{windowLabel(e)}</span>
              <span className="text-xs opacity-70">anotado {dateKeyOf(new Date(e.created_at), tz) === hoy ? "hoy" : slotLabel(e.created_at, tz)}</span>
            </div>
            {operador && (e.patient.phone_e164 || e.patient.email) && (
              <p className="mt-1 text-xs opacity-80">
                {[e.patient.phone_e164, e.patient.email].filter(Boolean).join(" · ")}
              </p>
            )}
            {e.notes !== null && <p className="mt-1 text-xs">Nota: {e.notes}</p>}
            {e.pending_offer !== null && (
              <p className="mt-1 text-xs">
                Oferta pendiente: {slotLabel(e.pending_offer.starts_at, tz)} ·{" "}
                {remaining(e.pending_offer.expires_at, ahora)}
              </p>
            )}
            {operador && (e.status === "waiting" || e.status === "offered") && (
              <div className="mt-2 flex flex-wrap gap-2">
                {e.status === "waiting" && (
                  <>
                    <Button variant="secondary" onClick={() => setDialogo({ tipo: "ofrecer", entry: e })}>
                      Ofrecer hueco
                    </Button>
                    <Button variant="secondary" onClick={() => setDialogo({ tipo: "editar", entry: e })}>
                      Editar
                    </Button>
                  </>
                )}
                {e.prioritized_at === null ? (
                  <Button variant="ghost" onClick={() => setDialogo({ tipo: "prioridad", entry: e })}>
                    Priorizar
                  </Button>
                ) : (
                  <Button variant="ghost" onClick={() => void ejecutar(() => unprioritizeEntry(e.id))}>
                    Quitar prioridad
                  </Button>
                )}
                <Button variant="ghost" onClick={() => setDialogo({ tipo: "retirar", entry: e })}>
                  Retirar
                </Button>
              </div>
            )}
          </li>
        ))}
      </ol>
      {cola.hasNextPage && (
        <div className="mt-3">
          <Button variant="secondary" disabled={cola.isFetchingNextPage} onClick={() => void cola.fetchNextPage()}>
            Cargar más
          </Button>
        </div>
      )}

      {dialogo?.tipo === "alta" && (
        <Modal title="Anotar en la lista de espera" onClose={cerrar}>
          <EntryForm
            today={hoy}
            onDone={cerrar}
            onShowExisting={(id) => {
              cerrar();
              setEstado("activas");
              setResaltada(id);
            }}
          />
        </Modal>
      )}
      {dialogo?.tipo === "editar" && (
        <Modal title="Editar la entrada" onClose={cerrar}>
          <EntryForm entry={dialogo.entry} today={hoy} onDone={cerrar} onShowExisting={setResaltada} />
        </Modal>
      )}
      {dialogo?.tipo === "ofrecer" && <OfferDialog entry={dialogo.entry} timezone={tz} onClose={cerrar} />}
      {dialogo?.tipo === "prioridad" && (
        <Modal title={`Priorizar a ${dialogo.entry.patient.full_name}`} onClose={cerrar}>
          <p className="mb-2 text-sm">
            La prioridad es una excepción al orden de llegada: queda registrada con tu usuario y el motivo.
          </p>
          <TextArea label="Motivo" maxLength={200} value={motivo} onChange={(e) => setMotivo(e.target.value)} />
          {errorAccion !== null && <Alert>{messageFor(errorAccion)}</Alert>}
          <div className="mt-3 flex justify-end gap-2">
            <Button variant="secondary" onClick={cerrar}>
              Cancelar
            </Button>
            <Button disabled={pending} onClick={() => void ejecutar(() => prioritizeEntry(dialogo.entry.id, motivo))}>
              Priorizar
            </Button>
          </div>
        </Modal>
      )}
      {dialogo?.tipo === "retirar" && (
        <Modal title="Retirar de la lista" onClose={cerrar}>
          <p className="text-sm">
            ¿Retirar a {dialogo.entry.patient.full_name} de la lista de espera?
            {dialogo.entry.status === "offered" ? " Su oferta pendiente se cierra y el hueco pasa al siguiente." : ""}
          </p>
          {errorAccion !== null && <Alert>{messageFor(errorAccion)}</Alert>}
          <div className="mt-3 flex justify-end gap-2">
            <Button variant="secondary" onClick={cerrar}>
              Cancelar
            </Button>
            <Button variant="danger" disabled={pending} onClick={() => void ejecutar(() => withdrawEntry(dialogo.entry.id))}>
              Retirar
            </Button>
          </div>
        </Modal>
      )}
    </div>
  );
}

export default WaitingListPage;
