import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "../shared/api/client";
import { messageFor } from "../shared/api/errors";
import { useAuth } from "../shared/auth/AuthProvider";
import { Alert, Button, TextField } from "../shared/ui";

/** Solo rutas internas: un `next` externo se ignora (evita open redirect). */
function safeNext(next: string | null): string {
  return next !== null && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

function LoginPage(): JSX.Element {
  const { session, state } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [bloqueoHasta, setBloqueoHasta] = useState<number | null>(null);
  const [, setTick] = useState(0);

  useEffect(() => {
    if (bloqueoHasta === null) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      if (Date.now() >= bloqueoHasta) {
        setBloqueoHasta(null);
      }
      setTick((t) => t + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [bloqueoHasta]);

  async function onSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    setEnviando(true);
    try {
      const user = await session.login(email.trim(), password);
      navigate(user.must_change_password ? "/cambiar-clave" : safeNext(params.get("next")), {
        replace: true
      });
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) {
        const segundos = e.retryAfterSeconds ?? 60;
        setBloqueoHasta(Date.now() + segundos * 1000);
        setError(`Demasiados intentos. Podés reintentar en ${segundos} segundos`);
      } else if (e instanceof ApiError && e.status === 401) {
        setError(messageFor(new ApiError(401, "invalid_credentials")));
      } else {
        setError(messageFor(e));
      }
    } finally {
      setEnviando(false);
    }
  }

  const bloqueado = bloqueoHasta !== null && Date.now() < bloqueoHasta;
  if (state.status === "authenticated" && state.user !== null && !enviando) {
    return (
      <Navigate
        to={state.user.must_change_password ? "/cambiar-clave" : safeNext(params.get("next"))}
        replace
      />
    );
  }
  return (
    <main className="flex min-h-screen items-center justify-center bg-enamel px-4">
      <form
        onSubmit={(e) => void onSubmit(e)}
        className="w-full max-w-sm space-y-4 rounded-lg bg-white p-6 shadow"
        noValidate
      >
        <h1 className="text-xl font-semibold text-dental-900">Ingresar</h1>
        <TextField
          label="Email"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <TextField
          label="Contraseña"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {error !== null && <Alert>{error}</Alert>}
        <Button type="submit" className="w-full" disabled={enviando || bloqueado}>
          Ingresar
        </Button>
      </form>
    </main>
  );
}

export default LoginPage;
