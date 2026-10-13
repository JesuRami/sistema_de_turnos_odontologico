/** Stub de agenda (grid custom real en C-06; smoke visual en C-01). */
function AgendaView(): JSX.Element {
  return (
    <section className="grid gap-2 p-6" aria-label="Agenda del día">
      <article className="rounded border border-dental-600/20 bg-white p-4 shadow-sm">
        <h2 className="font-medium">Agenda del día</h2>
        <p className="text-sm opacity-70">
          Vista multi-sillón (turnos reales desde C-04/C-05).
        </p>
      </article>
    </section>
  );
}

export default AgendaView;
