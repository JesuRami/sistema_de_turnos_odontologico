import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";
import { AuthProvider } from "./shared/auth/AuthProvider";
import { session } from "./shared/auth/session";

const rootElement: HTMLElement | null = document.getElementById("root");
if (rootElement === null) {
  throw new Error("root element no encontrado");
}

// D3: la agenda la miran varias personas a la vez → datos frescos y refetch al volver el foco.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, refetchOnWindowFocus: true, retry: 1 },
    mutations: { retry: false }
  }
});

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider session={session}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  </React.StrictMode>
);
