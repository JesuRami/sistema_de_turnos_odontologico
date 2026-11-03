/** Variables del E2E: credenciales solo por entorno (regla 6), datos sintéticos (regla 13). */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

function requerida(nombre: string): string {
  const valor = process.env[nombre];
  if (valor === undefined || valor === "") {
    throw new Error(`Falta la variable de entorno ${nombre} (ver frontend/README.md §E2E)`);
  }
  return valor;
}

/** Se lee al usarse (no al importar): `playwright test --list` no necesita credenciales. */
export function e2eEnv(): { baseURL: string; adminEmail: string; adminProvisional: string; password: string } {
  return {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    adminEmail: requerida("E2E_ADMIN_EMAIL"),
    /** Clave provisoria con la que el seed crea al admin. */
    adminProvisional: requerida("E2E_ADMIN_PASSWORD"),
    /** Clave definitiva que usan todos los usuarios del E2E tras el cambio obligatorio. */
    password: requerida("E2E_PASSWORD")
  };
}

export const STATE_PATH = fileURLToPath(new URL("./.state.json", import.meta.url));

export interface E2EState {
  run: string;
  professional: string;
  chair: string;
  patient: string;
  receptionEmail: string;
  receptionProvisional: string;
  perfPatient: string;
  perfAppointments: number;
}

export function readState(): E2EState {
  return JSON.parse(readFileSync(STATE_PATH, "utf8")) as E2EState;
}
