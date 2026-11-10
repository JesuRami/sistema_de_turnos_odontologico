/**
 * Aviso de presupuesto de WhatsApp para el admin (C-14, D8; SU-07). Solo informa: los envíos no se
 * cortan. Aparece al 80 % del umbral mensual y al superarlo.
 */
import { NavLink } from "react-router-dom";
import { useWhatsAppBudget } from "./api";

export function BudgetBanner({ enabled }: { enabled: boolean }): JSX.Element | null {
  const presupuesto = useWhatsAppBudget(enabled);
  const datos = presupuesto.data;
  if (!enabled || datos === undefined || (datos.status !== "warning" && datos.status !== "exceeded")) {
    return null;
  }
  const excedido = datos.status === "exceeded";
  return (
    <div
      role="status"
      className={`border-b px-4 py-2 text-sm print:hidden ${
        excedido ? "border-rose-300 bg-rose-50 text-rose-950" : "border-amber-300 bg-amber-50 text-amber-950"
      }`}
    >
      <strong>{excedido ? "Presupuesto de WhatsApp superado." : "Presupuesto de WhatsApp al 80 %."}</strong>{" "}
      {`Este mes: US$ ${datos.spent_usd} de US$ ${datos.threshold_usd ?? "—"}. Los recordatorios se siguen enviando.`}{" "}
      <NavLink to="/admin/reportes" className="underline">
        Ver reporte
      </NavLink>
    </div>
  );
}
