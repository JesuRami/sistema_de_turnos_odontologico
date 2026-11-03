/** Datos de la agenda que comparten el formulario y el detalle de turno. */
import type { Chair, Professional, ScheduleRule, UserRole } from "../../shared/api/types";

export interface AgendaContext {
  tz: string;
  role: UserRole;
  professionals: Professional[];
  chairs: Chair[];
  schedules: ScheduleRule[];
}
