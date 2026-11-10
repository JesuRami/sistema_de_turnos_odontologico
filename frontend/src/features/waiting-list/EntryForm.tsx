/**
 * Alta y edición de una entrada de la lista de espera (C-12; spec web/waiting-list).
 * Período obligatorio; franja y días opcionales; nota operativa sin datos personales.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError } from "../../shared/api/client";
import { messageFor } from "../../shared/api/errors";
import { useProfessionals } from "../../shared/api/queries";
import {
  firstError,
  validateDateRange,
  validateFreeText,
  validateTimeWindow
} from "../../shared/forms/validators";
import type { EntryPreferences, WaitingListEntry } from "../../shared/api/types";
import { Alert, Button, SelectField, TextArea, TextField } from "../../shared/ui";
import { PatientSearch, type PickedPatient } from "../patients/PatientPicker";
import { createEntry, updateEntry, waitlistKeys } from "./api";
import { WEEKDAYS } from "./format";

interface EntryFormProps {
  /** Sin `entry` es un alta. */
  entry?: WaitingListEntry;
  /** Fecha local de hoy (`YYYY-MM-DD`) para el período por defecto. */
  today: string;
  onDone: () => void;
  /** Ante `409 already_waiting`: abrir la entrada existente. */
  onShowExisting: (entryId: string) => void;
}

function addDaysIso(isoDate: string, days: number): string {
  const fecha = new Date(`${isoDate}T12:00:00Z`);
  fecha.setUTCDate(fecha.getUTCDate() + days);
  return fecha.toISOString().slice(0, 10);
}

function EntryForm({ entry, today, onDone, onShowExisting }: EntryFormProps): JSX.Element {
  const queryClient = useQueryClient();
  const profesionales = useProfessionals();
  const [patient, setPatient] = useState<PickedPatient | null>(
    entry !== undefined ? { id: entry.patient.id, full_name: entry.patient.full_name } : null
  );
  const [professionalId, setProfessionalId] = useState(entry?.professional_id ?? "");
  const [dateFrom, setDateFrom] = useState(entry?.date_from ?? today);
  const [dateTo, setDateTo] = useState(entry?.date_to ?? addDaysIso(today, 14));
  const [timeFrom, setTimeFrom] = useState(entry?.time_from?.slice(0, 5) ?? "");
  const [timeTo, setTimeTo] = useState(entry?.time_to?.slice(0, 5) ?? "");
  const [weekdays, setWeekdays] = useState<number[]>(entry?.weekdays ?? []);
  const [notes, setNotes] = useState(entry?.notes ?? "");
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [pending, setPending] = useState(false);

  function toggleDay(day: number): void {
    setWeekdays((actual) =>
      actual.includes(day) ? actual.filter((d) => d !== day) : [...actual, day].sort()
    );
  }

  async function onSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (entry === undefined && patient === null) {
      setError(new Error("Elegí un paciente"));
      return;
    }
    // C-14 (D11): mismas reglas que la API, antes de enviar (la API sigue siendo la autoridad).
    const invalido = firstError(
      validateDateRange(dateFrom, dateTo),
      validateTimeWindow(timeFrom, timeTo),
      validateFreeText(notes)
    );
    if (invalido !== null) {
      setError(new Error(invalido));
      return;
    }
    const prefs: EntryPreferences = {
      professional_id: professionalId === "" ? null : professionalId,
      date_from: dateFrom,
      date_to: dateTo,
      time_from: timeFrom === "" ? null : timeFrom,
      time_to: timeTo === "" ? null : timeTo,
      weekdays: weekdays.length > 0 ? weekdays : null
    };
    setPending(true);
    setError(null);
    try {
      if (entry === undefined) {
        await createEntry({ ...prefs, patient_id: patient?.id ?? "", notes: notes.trim() || null });
      } else {
        await updateEntry(entry.id, { ...prefs, notes: notes.trim() || null });
      }
      await queryClient.invalidateQueries({ queryKey: waitlistKeys.all });
      onDone();
    } catch (fallo) {
      setError(fallo instanceof Error ? fallo : new Error(String(fallo)));
    } finally {
      setPending(false);
    }
  }

  const existente =
    error instanceof ApiError && error.detail === "already_waiting"
      ? (error.extra.entry_id as string | undefined)
      : undefined;

  return (
    <form className="space-y-3" onSubmit={(e) => void onSubmit(e)}>
      {entry === undefined ? (
        patient === null ? (
          <PatientSearch onPick={setPatient} />
        ) : (
          <p className="text-sm">
            Paciente: <strong>{patient.full_name}</strong>{" "}
            <Button variant="ghost" onClick={() => setPatient(null)}>
              Cambiar
            </Button>
          </p>
        )
      ) : (
        <p className="text-sm">
          Paciente: <strong>{entry.patient.full_name}</strong>
        </p>
      )}
      <SelectField
        label="Profesional"
        value={professionalId}
        onChange={(e) => setProfessionalId(e.target.value)}
      >
        <option value="">Cualquiera</option>
        {(profesionales.data ?? [])
          .filter((p) => p.active)
          .map((p) => (
            <option key={p.id} value={p.id}>
              {p.display_name}
            </option>
          ))}
      </SelectField>
      <div className="grid grid-cols-2 gap-3">
        <TextField
          label="Desde"
          type="date"
          required
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
        />
        <TextField
          label="Hasta"
          type="date"
          required
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
        />
        <TextField
          label="Franja desde (opcional)"
          type="time"
          value={timeFrom}
          onChange={(e) => setTimeFrom(e.target.value)}
        />
        <TextField
          label="Franja hasta (opcional)"
          type="time"
          value={timeTo}
          onChange={(e) => setTimeTo(e.target.value)}
        />
      </div>
      <fieldset className="text-sm">
        <legend className="font-medium">Días (opcional; sin marcar = cualquiera)</legend>
        <div className="mt-1 flex flex-wrap gap-2">
          {WEEKDAYS.map((nombre, dia) => (
            <label key={nombre} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={weekdays.includes(dia)}
                onChange={() => toggleDay(dia)}
              />
              {nombre}
            </label>
          ))}
        </div>
      </fieldset>
      <TextArea
        label="Nota operativa (opcional, sin teléfonos ni DNI)"
        maxLength={200}
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
      />
      {error !== null && (
        <Alert>
          {error instanceof ApiError ? messageFor(error) : error.message}
          {existente !== undefined && (
            <>
              {" "}
              <Button variant="secondary" onClick={() => onShowExisting(existente)}>
                Ver la entrada existente
              </Button>
            </>
          )}
        </Alert>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          Cancelar
        </Button>
        <Button type="submit" disabled={pending}>
          {entry === undefined ? "Anotar" : "Guardar"}
        </Button>
      </div>
    </form>
  );
}

export default EntryForm;
