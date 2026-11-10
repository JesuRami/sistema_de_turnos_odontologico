/**
 * Políticas de la clínica (US-004). El admin edita; recepción solo consulta.
 * Los cambios afectan lo que se programe después (contrato de C-04/C-09).
 */
import { useEffect, useState, type FormEvent } from "react";
import { apiFetch } from "../../shared/api/client";
import { queryKeys, usePolicies } from "../../shared/api/queries";
import type { ClinicPolicies, ReminderStep } from "../../shared/api/types";
import { useAuth } from "../../shared/auth/AuthProvider";
import { Alert, Button, PageTitle, SelectField, TextField } from "../../shared/ui";
import { useSave } from "./useSave";

const CANAL: Record<ReminderStep["channel"], string> = { whatsapp: "WhatsApp", email: "Email" };

function describirPasos(pasos: readonly ReminderStep[]): string {
  const canales = new Set(pasos.map((p) => p.channel));
  const horas = pasos.map((p) => `${p.offset_h} h`);
  const lista = horas.length > 1 ? `${horas.slice(0, -1).join(", ")} y ${horas[horas.length - 1] ?? ""}` : horas[0] ?? "";
  return `${lista} antes (${[...canales].map((c) => CANAL[c]).join(" / ")})`;
}

function PoliciesPage(): JSX.Element {
  const { user } = useAuth();
  const policies = usePolicies();
  const esAdmin = user?.role === "admin";

  return (
    <section>
      <PageTitle>Políticas de la clínica</PageTitle>
      {policies.isError && <Alert>No se pudieron cargar las políticas.</Alert>}
      {policies.data !== undefined &&
        (esAdmin ? <PoliciesForm actuales={policies.data} /> : <PoliciesView p={policies.data} />)}
    </section>
  );
}

function PoliciesView({ p }: { p: ClinicPolicies }): JSX.Element {
  const filas: [string, string][] = [
    ["Ventana de cancelación", `${p.cancellation_window_hours} h`],
    ["Recordatorios", describirPasos(p.reminder_steps)],
    ["Tope de sobreturnos por profesional y día", String(p.max_overbookings_per_day)],
    ["Vigencia de ofertas de lista de espera", `${p.waitlist_offer_ttl_hours} h`],
    ["Teléfono de contacto", p.contact_phone ?? "Sin cargar"],
    [
      "Alerta de costo mensual de WhatsApp",
      p.whatsapp_monthly_alert_usd !== null ? `US$ ${p.whatsapp_monthly_alert_usd}` : "Sin alerta"
    ]
  ];
  return (
    <dl className="grid max-w-xl grid-cols-2 gap-x-4 gap-y-2 rounded bg-white p-4 text-sm shadow-sm">
      {filas.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="font-medium">{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function PoliciesForm({ actuales }: { actuales: ClinicPolicies }): JSX.Element {
  const save = useSave([queryKeys.policies]);
  const [p, setP] = useState<ClinicPolicies>(actuales);
  const [aviso, setAviso] = useState(false);
  const [errorAlerta, setErrorAlerta] = useState<string | null>(null);
  useEffect(() => setP(actuales), [actuales]);
  const set = <K extends keyof ClinicPolicies>(k: K, v: ClinicPolicies[K]): void => {
    setAviso(false);
    setP((prev) => ({ ...prev, [k]: v }));
  };
  const setPaso = (i: number, paso: ReminderStep): void =>
    set(
      "reminder_steps",
      p.reminder_steps.map((s, j) => (j === i ? paso : s))
    );

  async function guardar(e: FormEvent): Promise<void> {
    e.preventDefault();
    const body: Partial<ClinicPolicies> = {};
    if (p.cancellation_window_hours !== actuales.cancellation_window_hours) {
      body.cancellation_window_hours = p.cancellation_window_hours;
    }
    if (p.max_overbookings_per_day !== actuales.max_overbookings_per_day) {
      body.max_overbookings_per_day = p.max_overbookings_per_day;
    }
    if (p.waitlist_offer_ttl_hours !== actuales.waitlist_offer_ttl_hours) {
      body.waitlist_offer_ttl_hours = p.waitlist_offer_ttl_hours;
    }
    if (JSON.stringify(p.reminder_steps) !== JSON.stringify(actuales.reminder_steps)) {
      body.reminder_steps = p.reminder_steps;
    }
    // El servidor lo normaliza a E.164; en v1 no se borra (vacío = sin cambios).
    const telefono = (p.contact_phone ?? "").trim();
    if (telefono !== "" && telefono !== actuales.contact_phone) {
      body.contact_phone = telefono;
    }
    // C-14 (D8): umbral en USD; vacío o 0 apaga la alerta. Solo informa, no corta envíos.
    const alerta = (p.whatsapp_monthly_alert_usd ?? "").trim().replace(",", ".");
    const alertaNumero = alerta === "" ? 0 : Number(alerta);
    if (!Number.isFinite(alertaNumero) || alertaNumero < 0 || alertaNumero > 100_000) {
      setErrorAlerta("El umbral tiene que ser un monto en dólares entre 0 y 100000");
      return;
    }
    setErrorAlerta(null);
    if (alertaNumero !== Number(actuales.whatsapp_monthly_alert_usd ?? 0)) {
      body.whatsapp_monthly_alert_usd = alerta === "" ? "0" : alerta;
    }
    if (Object.keys(body).length === 0) {
      return;
    }
    if (await save.run(() => apiFetch("/api/clinic/policies", { method: "PATCH", body }))) {
      setAviso(true);
    }
  }

  return (
    <form onSubmit={(e) => void guardar(e)} className="max-w-xl space-y-3 rounded bg-white p-4 shadow-sm" noValidate>
      <TextField
        label="Ventana de cancelación (horas)"
        type="number"
        min={0}
        max={720}
        value={p.cancellation_window_hours}
        onChange={(e) => set("cancellation_window_hours", Number(e.target.value))}
      />
      <TextField
        label="Tope de sobreturnos por profesional y día"
        type="number"
        min={0}
        max={20}
        value={p.max_overbookings_per_day}
        onChange={(e) => set("max_overbookings_per_day", Number(e.target.value))}
      />
      <TextField
        label="Vigencia de ofertas de lista de espera (horas)"
        type="number"
        min={1}
        max={72}
        value={p.waitlist_offer_ttl_hours}
        onChange={(e) => set("waitlist_offer_ttl_hours", Number(e.target.value))}
      />
      <TextField
        label="Teléfono de contacto de la clínica"
        type="tel"
        autoComplete="off"
        maxLength={32}
        hint="Se muestra a los pacientes cuando tienen que llamar (link vencido o cancelación fuera de plazo)."
        value={p.contact_phone ?? ""}
        onChange={(e) => set("contact_phone", e.target.value)}
      />
      <TextField
        label="Alerta de costo mensual de WhatsApp (US$)"
        type="number"
        min={0}
        max={100000}
        step="0.01"
        hint="Avisa al admin al llegar al 80 % y al superarlo. No corta los envíos. Vacío o 0 = sin alerta."
        value={p.whatsapp_monthly_alert_usd ?? ""}
        onChange={(e) => set("whatsapp_monthly_alert_usd", e.target.value === "" ? null : e.target.value)}
      />
      {errorAlerta !== null && <Alert>{errorAlerta}</Alert>}
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Pasos de recordatorio</legend>
        {p.reminder_steps.map((paso, i) => (
          <div key={i} className="flex items-end gap-2">
            <TextField
              label="Horas antes"
              type="number"
              min={1}
              value={paso.offset_h}
              onChange={(e) => setPaso(i, { ...paso, offset_h: Number(e.target.value) })}
            />
            <SelectField
              label="Canal"
              value={paso.channel}
              onChange={(e) => setPaso(i, { ...paso, channel: e.target.value === "email" ? "email" : "whatsapp" })}
            >
              <option value="whatsapp">WhatsApp</option>
              <option value="email">Email</option>
            </SelectField>
            <Button
              variant="ghost"
              aria-label={`Quitar paso ${i + 1}`}
              disabled={p.reminder_steps.length <= 1}
              onClick={() => set("reminder_steps", p.reminder_steps.filter((_, j) => j !== i))}
            >
              Quitar
            </Button>
          </div>
        ))}
        <Button
          variant="secondary"
          disabled={p.reminder_steps.length >= 5}
          onClick={() => set("reminder_steps", [...p.reminder_steps, { offset_h: 1, channel: "whatsapp" }])}
        >
          Agregar paso
        </Button>
      </fieldset>
      {save.error !== null && <Alert>{save.error}</Alert>}
      {aviso && <Alert tone="success">Políticas guardadas</Alert>}
      <Button type="submit" disabled={save.pending}>
        Guardar políticas
      </Button>
    </form>
  );
}

export default PoliciesPage;
