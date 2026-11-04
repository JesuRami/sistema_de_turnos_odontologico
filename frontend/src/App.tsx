import { Route, Routes } from "react-router-dom";
import ChairsAdmin from "./features/admin/ChairsAdmin";
import PoliciesPage from "./features/admin/PoliciesPage";
import ProfessionalsAdmin from "./features/admin/ProfessionalsAdmin";
import SchedulesAdmin from "./features/admin/SchedulesAdmin";
import AgendaPage from "./features/agenda/AgendaPage";
import BlocksPage from "./features/blocks/BlocksPage";
import MergePatientsPage from "./features/patients/MergePatientsPage";
import ReportsPage from "./features/reports/ReportsPage";
import BookingPage from "./pages/BookingPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import LoginPage from "./pages/LoginPage";
import ManagePage from "./pages/ManagePage";
import { Forbidden, RequireRole, RequireSession } from "./shared/auth/guards";
import StaffLayout from "./shared/layout/StaffLayout";

/** Rutas de la SPA (D6). Públicas del paciente; el resto exige sesión y rol. */
function App(): JSX.Element {
  return (
    <Routes>
      {/* Públicas: reserva online (C-07) y gestión por token (C-08). */}
      <Route path="/b/:slug" element={<BookingPage />} />
      <Route path="/g/:token" element={<ManagePage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireSession />}>
        <Route path="/cambiar-clave" element={<ChangePasswordPage />} />
        <Route element={<StaffLayout />}>
          <Route path="/" element={<AgendaPage />} />
          <Route path="/bloqueos" element={<BlocksPage />} />
          <Route
            path="/politicas"
            element={
              <RequireRole roles={["admin", "recepcion"]}>
                <PoliciesPage />
              </RequireRole>
            }
          />
          <Route
            path="/pacientes/fusionar"
            element={
              <RequireRole roles={["admin", "recepcion"]}>
                <MergePatientsPage />
              </RequireRole>
            }
          />
          <Route
            path="/admin/profesionales"
            element={
              <RequireRole roles={["admin"]}>
                <ProfessionalsAdmin />
              </RequireRole>
            }
          />
          <Route
            path="/admin/sillones"
            element={
              <RequireRole roles={["admin"]}>
                <ChairsAdmin />
              </RequireRole>
            }
          />
          <Route
            path="/admin/horarios"
            element={
              <RequireRole roles={["admin"]}>
                <SchedulesAdmin />
              </RequireRole>
            }
          />
          <Route
            path="/admin/reportes"
            element={
              <RequireRole roles={["admin"]}>
                <ReportsPage />
              </RequireRole>
            }
          />
          <Route path="*" element={<Forbidden />} />
        </Route>
      </Route>
    </Routes>
  );
}

export default App;
