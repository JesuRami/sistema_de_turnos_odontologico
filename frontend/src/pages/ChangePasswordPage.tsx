import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, apiFetch } from "../shared/api/client";
import { messageFor } from "../shared/api/errors";
import { useAuth } from "../shared/auth/AuthProvider";
import { Alert, Button, TextField } from "../shared/ui";

const POLITICA =
  "La contraseña nueva debe tener entre 12 y 128 caracteres y ser distinta de la actual";

function motivo(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401 && error.detail === "invalid_credentials") {
      return "La contraseña actual no es correcta";
    }
    if (error.status === 422) {
      return POLITICA;
    }
  }
  return messageFor(error);
}

/** Cambio de contraseña (obligatorio con clave provisoria, spec web/staff-session). */
function ChangePasswordPage(): JSX.Element {
  const { session, user } = useAuth();
  const navigate = useNavigate();
  const [actual, setActual] = useState("");
  const [nueva, setNueva] = useState("");
  const [repetida, setRepetida] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function onSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    if (nueva !== repetida) {
      setError("Las contraseñas no coinciden");
      return;
    }
    setEnviando(true);
    try {
      await apiFetch("/api/auth/change-password", {
        method: "POST",
        body: { current_password: actual, new_password: nueva }
      });
      await session.reloadProfile();
      navigate("/", { replace: true });
    } catch (e) {
      setError(motivo(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-enamel px-4">
      <form
        onSubmit={(e) => void onSubmit(e)}
        className="w-full max-w-sm space-y-4 rounded-lg bg-white p-6 shadow"
        noValidate
      >
        <h1 className="text-xl font-semibold text-dental-900">Cambiar contraseña</h1>
        {user?.must_change_password === true && (
          <Alert tone="info">Antes de seguir tenés que reemplazar la contraseña provisoria.</Alert>
        )}
        <TextField
          label="Contraseña actual"
          type="password"
          autoComplete="current-password"
          value={actual}
          onChange={(e) => setActual(e.target.value)}
        />
        <TextField
          label="Contraseña nueva"
          type="password"
          autoComplete="new-password"
          hint="Mínimo 12 caracteres."
          value={nueva}
          onChange={(e) => setNueva(e.target.value)}
        />
        <TextField
          label="Repetir contraseña nueva"
          type="password"
          autoComplete="new-password"
          value={repetida}
          onChange={(e) => setRepetida(e.target.value)}
        />
        {error !== null && <Alert>{error}</Alert>}
        <Button type="submit" className="w-full" disabled={enviando}>
          Cambiar contraseña
        </Button>
      </form>
    </main>
  );
}

export default ChangePasswordPage;
