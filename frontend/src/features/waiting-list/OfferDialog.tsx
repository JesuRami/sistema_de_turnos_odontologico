/**
 * Oferta manual de un hueco a una entrada (C-12, D10; spec web/waiting-list).
 * Muestra los huecos libres de los próximos 14 días que respetan la preferencia; si la API pide
 * motivo de excepción a FIFO, lo pide y reintenta con él.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ApiError } from "../../shared/api/client";
import { messageFor } from "../../shared/api/errors";
import { useProfessionals } from "../../shared/api/queries";
import type { SlotCandidate, WaitingListEntry } from "../../shared/api/types";
import { useClock } from "../../shared/time/now";
import { Alert, Button, Modal, TextArea } from "../../shared/ui";
import { offerSlot, useSlots, waitlistKeys } from "./api";
import { slotLabel } from "./format";

const DIAS = 14;

interface OfferDialogProps {
  entry: WaitingListEntry;
  timezone: string;
  onClose: () => void;
}

function OfferDialog({ entry, timezone, onClose }: OfferDialogProps): JSX.Element {
  const clock = useClock();
  const queryClient = useQueryClient();
  const [range] = useState(() => {
    const desde = clock();
    return { from: desde, to: new Date(desde.getTime() + DIAS * 24 * 3_600_000) };
  });
  const huecos = useSlots(entry.id, range);
  const profesionales = useProfessionals();
  const nombres = useMemo(
    () => new Map((profesionales.data ?? []).map((p) => [p.id, p.display_name])),
    [profesionales.data]
  );
  const [elegido, setElegido] = useState<SlotCandidate | null>(null);
  const [pideMotivo, setPideMotivo] = useState(false);
  const [motivo, setMotivo] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);

  async function ofrecer(): Promise<void> {
    if (elegido === null) {
      return;
    }
    setPending(true);
    setError(null);
    try {
      await offerSlot(entry.id, {
        professional_id: elegido.professional_id,
        chair_id: elegido.chair_id,
        starts_at: elegido.starts_at,
        ...(pideMotivo ? { fifo_skip_reason: motivo.trim() } : {})
      });
      await queryClient.invalidateQueries({ queryKey: waitlistKeys.all });
      onClose();
    } catch (fallo) {
      if (fallo instanceof ApiError && fallo.detail === "fifo_skip_reason_required" && !pideMotivo) {
        setPideMotivo(true);
      } else {
        setError(fallo);
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <Modal title={`Ofrecer un hueco a ${entry.patient.full_name}`} onClose={onClose}>
      {huecos.isPending && <p className="text-sm">Buscando huecos libres…</p>}
      {huecos.isError && <Alert>{messageFor(huecos.error)}</Alert>}
      {huecos.isSuccess && huecos.data.items.length === 0 && (
        <p className="text-sm">No hay huecos libres que respeten su preferencia en los próximos {DIAS} días.</p>
      )}
      {huecos.isSuccess && huecos.data.items.length > 0 && (
        <ul className="max-h-64 space-y-1 overflow-y-auto" aria-label="Huecos libres">
          {huecos.data.items.map((h) => {
            const clave = `${h.starts_at}-${h.chair_id}`;
            const activo = elegido !== null && `${elegido.starts_at}-${elegido.chair_id}` === clave;
            return (
              <li key={clave}>
                <Button
                  variant={activo ? "primary" : "secondary"}
                  aria-pressed={activo}
                  onClick={() => {
                    setElegido(h);
                    setPideMotivo(false);
                  }}
                >
                  {slotLabel(h.starts_at, timezone)} · {nombres.get(h.professional_id) ?? "Profesional"}
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      {pideMotivo && (
        <div className="mt-3 space-y-2">
          <Alert tone="info">
            Hay pacientes antes en la cola para este hueco. Para saltear el orden de llegada indicá
            el motivo (queda registrado).
          </Alert>
          <TextArea
            label="Motivo de la excepción"
            maxLength={200}
            value={motivo}
            onChange={(e) => setMotivo(e.target.value)}
          />
        </div>
      )}
      {error !== null && (
        <div className="mt-3">
          <Alert>{messageFor(error)}</Alert>
        </div>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancelar
        </Button>
        <Button disabled={elegido === null || pending} onClick={() => void ofrecer()}>
          {pideMotivo ? "Ofrecer igual" : "Ofrecer"}
        </Button>
      </div>
    </Modal>
  );
}

export default OfferDialog;
