/** Cliente tipado de la historia clínica (C-15). Nada se persiste en el navegador (D11). */
import { apiFetch } from "../../shared/api/client";
import { chunk, type Dentition } from "./fdi";
import type {
  Anamnesis,
  AnamnesisAnswers,
  Attachment,
  AttachmentKind,
  ClinicalRecord,
  Condition,
  Evolution,
  OdontogramEntry,
  OdontogramState,
  Page,
  PlanItemInput,
  PlanSummary
} from "./types";

export const MAX_BATCH = 32;

export function getRecord(patientId: string): Promise<ClinicalRecord> {
  return apiFetch<ClinicalRecord>(`/api/patients/${patientId}/clinical-record`);
}

export function openRecord(patientId: string): Promise<{ record_id: string }> {
  return apiFetch(`/api/patients/${patientId}/clinical-record`, { method: "POST" });
}

export function getConditions(): Promise<{ items: Condition[] }> {
  return apiFetch("/api/odontogram/conditions");
}

export function getOdontogram(recordId: string, dentition: Dentition): Promise<OdontogramState> {
  return apiFetch(`/api/clinical-records/${recordId}/odontogram`, { query: { dentition } });
}

/**
 * Envía el borrador en lotes de ≤ 32. Devuelve las entradas no confirmadas (vacío si todo salió
 * bien) para que la UI conserve el borrador de lo que falló.
 */
export async function saveOdontogram(
  recordId: string,
  entries: readonly OdontogramEntry[]
): Promise<{ pending: OdontogramEntry[]; error: unknown }> {
  const lotes = chunk(entries, MAX_BATCH);
  for (let i = 0; i < lotes.length; i += 1) {
    try {
      await apiFetch(`/api/clinical-records/${recordId}/odontogram/events`, {
        method: "POST",
        body: { entries: lotes[i] }
      });
    } catch (error) {
      return { pending: lotes.slice(i).flat(), error };
    }
  }
  return { pending: [], error: null };
}

export function listEvolutions(recordId: string, cursor?: string): Promise<Page<Evolution>> {
  return apiFetch(`/api/clinical-records/${recordId}/evolutions`, { query: { cursor } });
}

export function createEvolution(recordId: string, body: string): Promise<Evolution> {
  return apiFetch(`/api/clinical-records/${recordId}/evolutions`, {
    method: "POST",
    body: { body }
  });
}

export function createCorrection(
  recordId: string,
  evolutionId: string,
  reason: string,
  body: string
): Promise<Evolution> {
  return apiFetch(`/api/clinical-records/${recordId}/evolutions/${evolutionId}/corrections`, {
    method: "POST",
    body: { reason, body }
  });
}

export function saveAnamnesis(
  recordId: string,
  expectedVersion: number,
  answers: AnamnesisAnswers
): Promise<Anamnesis> {
  return apiFetch(`/api/clinical-records/${recordId}/anamnesis`, {
    method: "POST",
    body: { expected_version: expectedVersion, answers }
  });
}

export function listAttachments(recordId: string): Promise<Page<Attachment>> {
  return apiFetch(`/api/clinical-records/${recordId}/attachments`);
}

export function uploadAttachment(
  recordId: string,
  file: File,
  kind: AttachmentKind
): Promise<Attachment> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);
  return apiFetch(`/api/clinical-records/${recordId}/attachments`, { method: "POST", body: form });
}

/** Descarga por blob: el contenido nunca pasa por almacenamiento del navegador (D11). */
export function downloadAttachment(recordId: string, attachmentId: string): Promise<Blob> {
  return apiFetch(`/api/clinical-records/${recordId}/attachments/${attachmentId}/content`, {
    responseType: "blob"
  });
}

export function removeAttachment(
  recordId: string,
  attachmentId: string,
  reason: string
): Promise<unknown> {
  return apiFetch(`/api/clinical-records/${recordId}/attachments/${attachmentId}/removal`, {
    method: "POST",
    body: { reason }
  });
}

export function listPlans(recordId: string): Promise<Page<PlanSummary>> {
  return apiFetch(`/api/clinical-records/${recordId}/treatment-plans`);
}

export function createPlan(
  recordId: string,
  title: string,
  items: readonly PlanItemInput[]
): Promise<unknown> {
  return apiFetch(`/api/clinical-records/${recordId}/treatment-plans`, {
    method: "POST",
    body: { title, items }
  });
}

export function planPdf(recordId: string, planId: string, version: number): Promise<Blob> {
  return apiFetch(
    `/api/clinical-records/${recordId}/treatment-plans/${planId}/versions/${version}/pdf`,
    { responseType: "blob" }
  );
}
