/** Cliente de la gestión por token (C-08). Anónimo y sin storage: el token solo vive en la URL. */
import { publicFetch } from "../../shared/api/public";
import type { ManageActionRequest, ManageAvailability, ManageView } from "./types";

const base = (token: string): string => `/api/manage/${encodeURIComponent(token)}`;

export function fetchManageView(token: string): Promise<ManageView> {
  return publicFetch<ManageView>(base(token));
}

export function fetchManageAvailability(
  token: string,
  range: { from: Date; to: Date }
): Promise<ManageAvailability> {
  return publicFetch<ManageAvailability>(`${base(token)}/availability`, {
    query: { from: range.from.toISOString(), to: range.to.toISOString() }
  });
}

export function sendManageAction(token: string, action: ManageActionRequest): Promise<ManageView> {
  return publicFetch<ManageView>(base(token), { method: "PATCH", body: action });
}
