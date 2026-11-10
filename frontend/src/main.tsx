import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";
import { retryDelay, shouldRetry } from "./shared/api/retry";
import { AuthProvider } from "./shared/auth/AuthProvider";
import { session } from "./shared/auth/session";
import { installBrowserListeners } from "./shared/network/status";
import { startRetryLoop } from "./shared/offline/retryQueue";
import { ErrorBoundary } from "./shared/ui/ErrorBoundary";

const rootElement: HTMLElement | null = document.getElementById("root");
if (rootElement === null) {
  throw new Error("root element no encontrado");
}

// D3: la agenda la miran varias personas a la vez → datos frescos y refetch al volver el foco.
// C-14 (D11): solo se reintenta lo que puede salir bien solo (red, 5xx, 429, carrera de locks),
// con backoff; un 4xx de negocio se muestra de inmediato. Al volver la red TanStack refresca solo.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
      retry: shouldRetry,
      retryDelay: (intento, error) => retryDelay(intento, error)
    },
    mutations: { retry: false }
  }
});

// SU-06: estado de red del navegador y cola de reintentos de recepción.
installBrowserListeners();
startRetryLoop();

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider session={session}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>
);
