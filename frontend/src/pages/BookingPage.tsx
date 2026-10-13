import { useParams } from "react-router-dom";

function BookingPage(): JSX.Element {
  const { slug } = useParams<{ slug: string }>();
  return (
    <main className="min-h-screen bg-enamel px-6 py-10">
      <h1 className="text-xl font-semibold text-dental-900">
        Reservar turno — {slug}
      </h1>
      <p className="mt-2 text-sm">Reserva online 24/7 (flujo completo en C-07).</p>
    </main>
  );
}

export default BookingPage;
