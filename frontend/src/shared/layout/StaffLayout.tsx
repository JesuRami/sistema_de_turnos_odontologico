import { NavLink, Outlet, useNavigate } from "react-router-dom";
import type { UserRole } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { Button } from "../ui";

interface NavItem {
  to: string;
  label: string;
  roles: readonly UserRole[];
}

const TODOS: readonly UserRole[] = ["admin", "recepcion", "odontologo"];

export const NAV: readonly NavItem[] = [
  { to: "/", label: "Agenda", roles: TODOS },
  { to: "/bloqueos", label: "Bloqueos", roles: TODOS },
  { to: "/pacientes/fusionar", label: "Fusionar pacientes", roles: ["admin", "recepcion"] },
  { to: "/politicas", label: "Políticas", roles: ["admin", "recepcion"] },
  { to: "/admin/profesionales", label: "Profesionales", roles: ["admin"] },
  { to: "/admin/sillones", label: "Sillones", roles: ["admin"] },
  { to: "/admin/horarios", label: "Horarios", roles: ["admin"] }
];

const ROL: Record<UserRole, string> = {
  admin: "Admin",
  recepcion: "Recepción",
  odontologo: "Odontólogo/a"
};

/** Marco de las pantallas del personal: menú por rol y cierre de sesión. */
function StaffLayout(): JSX.Element {
  const { user, session } = useAuth();
  const navigate = useNavigate();
  const rol = user?.role;

  async function salir(): Promise<void> {
    await session.logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="min-h-screen bg-enamel text-dental-900">
      <header className="flex flex-wrap items-center gap-4 bg-dental-600 px-4 py-2 text-white">
        <span className="font-semibold">Turnos</span>
        <nav aria-label="Secciones" className="flex flex-1 flex-wrap gap-1">
          {NAV.filter((item) => rol !== undefined && item.roles.includes(rol)).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `rounded px-2 py-1 text-sm ${isActive ? "bg-white/20 font-medium" : "hover:bg-white/10"}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <span className="text-xs opacity-90">
          {user?.email} · {rol !== undefined ? ROL[rol] : ""}
        </span>
        <Button variant="secondary" onClick={() => void salir()}>
          Cerrar sesión
        </Button>
      </header>
      <main className="p-4">
        <Outlet />
      </main>
    </div>
  );
}

export default StaffLayout;
