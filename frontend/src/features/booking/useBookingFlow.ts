/**
 * Estado del flujo de reserva (D12): `useReducer` con pasos `professional → day → time →
 * contact → done`. Solo en memoria: ni los datos ni el token tocan `localStorage` ni
 * `sessionStorage`. Volver atrás cambia el paso pero conserva lo elegido.
 */
import { useReducer, type Dispatch } from "react";
import type { DateKey } from "../../shared/time/zoned";
import type { BookingResult } from "./types";

export type BookingStep = "professional" | "day" | "time" | "contact" | "done";

export interface BookingFlowState {
  step: BookingStep;
  professionalId: string | null;
  day: DateKey | null;
  /** Inicio ISO del hueco elegido. */
  slot: string | null;
  /** Ventana de 14 días que se está mirando (0 = desde hoy). */
  windowIndex: number;
  result: BookingResult | null;
}

export type BookingAction =
  | { type: "professional"; id: string }
  | { type: "day"; day: DateKey }
  | { type: "slot"; startsAt: string }
  | { type: "window"; index: number }
  | { type: "back" }
  | { type: "done"; result: BookingResult };

const ORDER: readonly BookingStep[] = ["professional", "day", "time", "contact"];

export function initialFlow(singleProfessionalId: string | null = null): BookingFlowState {
  return {
    step: singleProfessionalId === null ? "professional" : "day",
    professionalId: singleProfessionalId,
    day: null,
    slot: null,
    windowIndex: 0,
    result: null
  };
}

export function bookingReducer(state: BookingFlowState, action: BookingAction): BookingFlowState {
  switch (action.type) {
    case "professional":
      // Otro profesional invalida día y horario elegidos.
      return state.professionalId === action.id
        ? { ...state, step: "day" }
        : { ...state, step: "day", professionalId: action.id, day: null, slot: null, windowIndex: 0 };
    case "day":
      return state.day === action.day
        ? { ...state, step: "time" }
        : { ...state, step: "time", day: action.day, slot: null };
    case "slot":
      return { ...state, step: "contact", slot: action.startsAt };
    case "window":
      return { ...state, windowIndex: action.index };
    case "back": {
      const anterior = ORDER[ORDER.indexOf(state.step) - 1];
      return anterior === undefined ? state : { ...state, step: anterior };
    }
    case "done":
      return { ...state, step: "done", result: action.result };
  }
}

/** Con un solo profesional el primer paso no existe: no se puede volver a él. */
export function useBookingFlow(
  singleProfessionalId: string | null
): [BookingFlowState, Dispatch<BookingAction>] {
  return useReducer(bookingReducer, singleProfessionalId, initialFlow);
}
