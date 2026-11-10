import { describe, expect, it } from "vitest";
import { ApiError } from "./client";
import { isRetryable, MAX_RETRIES, retryDelay, shouldRetry } from "./retry";

describe("política de reintentos (C-14)", () => {
  it.each([
    [new ApiError(0, "network_error"), true],
    [new ApiError(503, "db_unavailable"), true],
    [new ApiError(500, "internal_error"), true],
    [new ApiError(429, "rate_limited"), true],
    [new ApiError(409, "concurrent_update"), true],
    [new ApiError(409, "slot_taken"), false],
    [new ApiError(422, "validation_error"), false],
    [new ApiError(401, "token_expired"), false],
    [new ApiError(403, "forbidden_role"), false],
    [new ApiError(501, "http_501"), false],
    [new Error("cualquiera"), false]
  ])("%o reintentable = %s", (error, esperado) => {
    expect(isRetryable(error)).toBe(esperado);
  });

  it("corta a los MAX_RETRIES intentos", () => {
    const red = new ApiError(0, "network_error");
    expect(shouldRetry(MAX_RETRIES - 1, red)).toBe(true);
    expect(shouldRetry(MAX_RETRIES, red)).toBe(false);
  });

  it("respeta Retry-After y lo acota a un minuto", () => {
    expect(retryDelay(0, new ApiError(429, "rate_limited", {}, 7))).toBe(7000);
    expect(retryDelay(0, new ApiError(503, "db_timeout", {}, 3600))).toBe(60_000);
  });

  it("backoff exponencial con jitter y techo", () => {
    const sinJitter = (): number => 0.5;
    expect(retryDelay(0, undefined, sinJitter)).toBe(1000);
    expect(retryDelay(2, undefined, sinJitter)).toBe(4000);
    expect(retryDelay(10, undefined, sinJitter)).toBe(15_000);
    expect(retryDelay(1, undefined, () => 0)).toBe(1600);
    expect(retryDelay(1, undefined, () => 1)).toBe(2400);
  });
});
