import { useEffect, useState } from "react";
import { fetchHealth } from "../api/client";
import AgendaView from "../features/agenda/AgendaView";

function AgendaPage(): JSX.Element {
  const [apiStatus, setApiStatus] = useState<string>("verificando…");

  useEffect(() => {
    fetchHealth()
      .then((health) => setApiStatus(health.status))
      .catch(() => setApiStatus("sin conexión"));
  }, []);

  return (
    <main className="min-h-screen bg-enamel text-dental-900">
      <header className="bg-dental-600 px-6 py-4 text-white">
        <h1 className="text-xl font-semibold">Agenda</h1>
        <p className="text-sm opacity-80">API: {apiStatus}</p>
      </header>
      <AgendaView />
    </main>
  );
}

export default AgendaPage;
