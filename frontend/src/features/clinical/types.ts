/** Tipos del borde clínico (C-15), espejo de `backend/app/modules/clinical/schemas.py`. */
import type { Dentition, Surface } from "./fdi";

export interface ClinicalRecord {
  record_id: string;
  patient_id: string;
  patient_name: string;
  patient_archived: boolean;
  created_at: string;
  anamnesis: Anamnesis | null;
  evolutions_count: number;
  attachments_count: number;
  plans_count: number;
}

export interface Anamnesis {
  id: string;
  version: number;
  answers: Record<string, unknown>;
  created_by_user_id: string;
  created_at: string;
}

export interface Condition {
  id: string;
  code: string;
  label: string;
  category: string;
  scope: "surface" | "tooth";
  active: boolean;
}

export interface SurfaceState {
  surface: Surface;
  condition_id: string | null;
  condition_code: string | null;
  condition_label: string | null;
  event_id: string | null;
  recorded_at: string | null;
}

export interface ToothState {
  tooth: number;
  surfaces: SurfaceState[];
}

export interface OdontogramState {
  dentition: Dentition;
  teeth: ToothState[];
}

export interface OdontogramEntry {
  tooth: number;
  surface: Surface;
  condition_id: string | null;
}

export interface Evolution {
  id: string;
  record_id: string;
  kind: "entry" | "correction";
  body: string;
  appointment_id: string | null;
  professional_id: string;
  created_by_user_id: string;
  signed_at: string;
  content_sha256: string;
  corrects_evolution_id: string | null;
  reason: string | null;
  corrected_by: string | null;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface AnamnesisAnswers {
  allergies: string[];
  medications: string[];
  systemic_conditions: string[];
  pregnant: boolean | null;
  smoker: boolean;
  anticoagulants: boolean;
  observations: string;
}

export type AttachmentKind = "xray" | "photo" | "document";

export interface Attachment {
  id: string;
  kind: AttachmentKind;
  content_type: string;
  size_bytes: number;
  display_name: string;
  evolution_id: string | null;
  created_by_user_id: string;
  created_at: string;
  removed: boolean;
  removal_reason: string | null;
  removed_at: string | null;
}

export interface PlanSummary {
  id: string;
  title: string;
  created_at: string;
  latest_version: number;
  total_cents: number;
  decision: string | null;
}

export interface PlanItemInput {
  phase: number;
  description: string;
  quantity: number;
  unit_price_cents: number;
}
