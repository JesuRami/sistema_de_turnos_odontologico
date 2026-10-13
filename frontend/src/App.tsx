import { Route, Routes } from "react-router-dom";
import AgendaPage from "./pages/AgendaPage";
import BookingPage from "./pages/BookingPage";
import LoginPage from "./pages/LoginPage";
import ManagePage from "./pages/ManagePage";

function App(): JSX.Element {
  return (
    <Routes>
      {/* Públicas: reserva online y gestión por token (paciente, sin login). */}
      <Route path="/b/:slug" element={<BookingPage />} />
      <Route path="/g/:token" element={<ManagePage />} />
      {/* Autenticadas (guard real en C-03; hoy solo layout). */}
      <Route path="/" element={<AgendaPage />} />
      <Route path="/login" element={<LoginPage />} />
    </Routes>
  );
}

export default App;
