/**
 * Descarga de archivos con la sesión del usuario (C-13, D10): el access token va en
 * el header, nunca en la URL, y el archivo se guarda desde un Blob en memoria.
 */
import { apiFetch, type Query } from "../../shared/api/client";

export async function downloadFile(path: string, query: Query, filename: string): Promise<void> {
  const blob = await apiFetch<Blob>(path, { query, responseType: "blob" });
  const url = URL.createObjectURL(blob);
  try {
    const enlace = document.createElement("a");
    enlace.href = url;
    enlace.download = filename;
    document.body.appendChild(enlace);
    enlace.click();
    enlace.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
