/** Setup de Vitest: matchers de DOM, red simulada con MSW y limpieza entre tests. */
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { networkStatus } from "../shared/network/status";
import { retryQueue } from "../shared/offline/retryQueue";
import { server } from "./server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  // C-14: stores de la pestaña (red y cola de reintentos) limpios entre tests.
  networkStatus.reset();
  retryQueue.clear();
});
afterAll(() => server.close());
