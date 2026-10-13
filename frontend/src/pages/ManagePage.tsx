import { useParams } from "react-router-dom";

function ManagePage(): JSX.Element {
  const { token } = useParams<{ token: string }>();
  return (
    <main className="min-h-screen bg-enamel px-6 py-10">
      <h1 className="text-xl font-semibold text-dental-900">Gestionar mi turno</h1>
      <p className="mt-2 text-sm">
        Token: {token} — confirmación y reprogramación (C-08).
      </p>
    </main>
  );
}

export default ManagePage;
