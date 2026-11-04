import { describe, expect, it } from "vitest";
import { bookingReducer, initialFlow, type BookingFlowState } from "./useBookingFlow";

const SLOT = "2030-01-07T13:00:00Z";

describe("bookingReducer", () => {
  it("arranca en profesional, o en día si hay uno solo", () => {
    expect(initialFlow().step).toBe("professional");
    expect(initialFlow("prof-1")).toMatchObject({ step: "day", professionalId: "prof-1" });
  });

  it("avanza profesional → día → hora → contacto", () => {
    let s: BookingFlowState = initialFlow();
    s = bookingReducer(s, { type: "professional", id: "prof-1" });
    expect(s.step).toBe("day");
    s = bookingReducer(s, { type: "day", day: "2030-01-07" });
    expect(s.step).toBe("time");
    s = bookingReducer(s, { type: "slot", startsAt: SLOT });
    expect(s).toMatchObject({ step: "contact", professionalId: "prof-1", day: "2030-01-07", slot: SLOT });
  });

  it("volver conserva lo elegido y no pasa del primer paso", () => {
    let s = initialFlow();
    s = bookingReducer(s, { type: "professional", id: "prof-1" });
    s = bookingReducer(s, { type: "day", day: "2030-01-07" });
    s = bookingReducer(s, { type: "slot", startsAt: SLOT });

    s = bookingReducer(s, { type: "back" });
    expect(s).toMatchObject({ step: "time", slot: SLOT, day: "2030-01-07" });
    s = bookingReducer(bookingReducer(s, { type: "back" }), { type: "back" });
    expect(s.step).toBe("professional");
    expect(bookingReducer(s, { type: "back" }).step).toBe("professional");
  });

  it("cambiar de profesional descarta día y horario; elegir el mismo no", () => {
    let s = initialFlow();
    s = bookingReducer(s, { type: "professional", id: "prof-1" });
    s = bookingReducer(s, { type: "day", day: "2030-01-07" });
    s = bookingReducer(s, { type: "slot", startsAt: SLOT });

    const mismo = bookingReducer({ ...s, step: "professional" }, { type: "professional", id: "prof-1" });
    expect(mismo).toMatchObject({ day: "2030-01-07", slot: SLOT });
    const otro = bookingReducer({ ...s, step: "professional" }, { type: "professional", id: "prof-2" });
    expect(otro).toMatchObject({ professionalId: "prof-2", day: null, slot: null, windowIndex: 0 });
  });

  it("cambiar de día descarta el horario", () => {
    let s = initialFlow("prof-1");
    s = bookingReducer(s, { type: "day", day: "2030-01-07" });
    s = bookingReducer(s, { type: "slot", startsAt: SLOT });

    const otro = bookingReducer({ ...s, step: "day" }, { type: "day", day: "2030-01-08" });

    expect(otro).toMatchObject({ step: "time", day: "2030-01-08", slot: null });
  });
});
