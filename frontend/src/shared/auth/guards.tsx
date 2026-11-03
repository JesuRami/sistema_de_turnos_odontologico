/**
 * Guards de rutas del personal (D6). Ocultan lo que el rol no puede ver; la
 * autorización real la sigue haciendo la API.
 */
import type { ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import type { UserRole } from "../api/types";
import { useAuth } from "./AuthProvider";

export function RequireSession(): JSX.Element {
  const { state } = useAuth();
  const location = useLocation();
  if (state.status === "unknown") {
    return <p className="p-6 text-sm">Cargando…</p>;
  }
  if (state.status === "anonymous" || state.user === null) {
    const next = encodeURIComponent(`${location.pathname}${location.search}`);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  if (state.user.must_change_password && location.pathname !== "/cambiar-clave") {
    return <Navigate to="/cambiar-clave" replace />;
  }
  return <Outlet />;
}

export function Forbidden(): JSX.Element {
  return (
    <section className="p-6">
      <p role="alert" className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm">
        No tenés permiso para esta sección
      </p>
    </section>
  );
}

export function RequireRole({
  roles,
  children
}: {
  roles: readonly UserRole[];
  children: ReactNode;
}): JSX.Element {
  const { user } = useAuth();
  if (user === null || !roles.includes(user.role)) {
    return <Forbidden />;
  }
  return <>{children}</>;
}

export function useRole(): UserRole | null {
  return useAuth().user?.role ?? null;
}
