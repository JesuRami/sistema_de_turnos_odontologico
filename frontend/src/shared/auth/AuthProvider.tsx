/**
 * Provider de la sesión (D1): conecta la sesión con el cliente API y con React.
 * Al cerrar sesión descarta las cachés de datos (spec web/staff-session §Logout).
 */
import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode
} from "react";
import { configureApi } from "../api/client";
import type { UserProfile } from "../api/types";
import type { Session, SessionState } from "./session";

interface AuthContextValue {
  state: SessionState;
  session: Session;
  user: UserProfile | null;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({
  session,
  children
}: {
  session: Session;
  children: ReactNode;
}): JSX.Element {
  const queryClient = useQueryClient();
  const state = useSyncExternalStore(session.subscribe, session.getState, session.getState);

  useEffect(() => {
    configureApi({
      getAccess: session.getAccess,
      refresh: () => session.refreshAccess(),
      onUnauthorized: session.expire
    });
  }, [session]);

  useEffect(() => {
    if (session.getState().status === "unknown") {
      void session.bootstrap();
    }
  }, [session]);

  useEffect(() => {
    if (state.status === "anonymous") {
      queryClient.clear();
    }
  }, [state.status, queryClient]);

  const value = useMemo(() => ({ state, session, user: state.user }), [state, session]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth fuera de AuthProvider");
  }
  return value;
}
