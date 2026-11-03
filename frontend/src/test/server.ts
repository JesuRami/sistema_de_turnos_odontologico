/** Servidor MSW compartido: cada test registra sus handlers con `server.use(...)`. */
import { setupServer } from "msw/node";

export const server = setupServer();
