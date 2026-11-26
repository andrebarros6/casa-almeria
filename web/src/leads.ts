// Lead tracker: stages, the "Em processo" table rows, next actions and the contact message.
// Pure logic, no DOM or network; unit-tested.

import { type Card, formatPrice, isLiked, place } from "./logic";

export type Stage =
  | "interessa"
  | "contactado"
  | "respondeu"
  | "visita"
  | "visitado"
  | "candidatura"
  | "fechado"
  | "sem_resposta"
  | "ja_alugado"
  | "descartado";

/** Stages stored in the `leads` table ("interessa" is implied by a ❤️). */
export type StoredStage = Exclude<Stage, "interessa">;

export interface Lead {
  group_id: string;
  stage: StoredStage;
  stage_at: string;
  next_action_at: string | null;
  reason: string | null;
  updated_by: string;
  updated_at: string;
}

export interface LeadEvent {
  group_id: string;
  user_email: string;
  kind: "stage" | "contact" | "note";
  body: string | null;
  at: string;
}

export interface DocItem {
  key: string;
  ready: boolean;
  note: string | null;
}

export const STAGES: { key: Stage; label: string; active: boolean }[] = [
  { key: "interessa", label: "Interessa", active: true },
  { key: "contactado", label: "Contactado", active: true },
  { key: "respondeu", label: "Respondeu", active: true },
  { key: "visita", label: "Visita marcada", active: true },
  { key: "visitado", label: "Visitado", active: true },
  { key: "candidatura", label: "Candidatura", active: true },
  { key: "fechado", label: "Fechado ✅", active: true },
  { key: "sem_resposta", label: "Sem resposta", active: false },
  { key: "ja_alugado", label: "Já alugado", active: false },
  { key: "descartado", label: "Descartado", active: false },
];

export const STAGE_LABELS = Object.fromEntries(STAGES.map((s) => [s.key, s.label])) as Record<
  Stage,
  string
>;

export const DISCARD_REASONS = ["Caro demais", "Zona", "Estado da casa", "Senhorio", "Outra"];

/** Household documents Spanish landlords usually ask for. */
export const DOCUMENTS: { key: string; label: string }[] = [
  { key: "dni_nie", label: "DNI / NIE" },
  { key: "nominas", label: "Nóminas (últimos 3 meses)" },
  { key: "contrato_trabajo", label: "Contrato de trabajo" },
  { key: "renta", label: "Declaración de la renta" },
  { key: "aval", label: "Aval bancario (se pedirem)" },
  { key: "fianza", label: "Fianza + 1.º mês disponível" },
];

const DAY_MS = 86_400_000;

export function stageOf(card: Card, leads: Map<string, Lead>): Stage | null {
  const lead = leads.get(card.groupId);
  if (lead) return lead.stage;
  return isLiked(card) ? "interessa" : null;
}

export function isActive(stage: Stage): boolean {
  return STAGES.find((s) => s.key === stage)?.active ?? false;
}

export interface Row {
  card: Card;
  stage: Stage;
  lead: Lead | null;
  lastEvent: LeadEvent | null;
}

export interface RowOptions {
  showFinished: boolean;
  stage: Stage | null;
}

/** What needs you first: upcoming visits, replies waiting on you, then the rest. */
function priority(row: Row, now: Date): [number, number] {
  const since = row.lead ? new Date(row.lead.stage_at).getTime() : 0;
  switch (row.stage) {
    case "visita": {
      const at = row.lead?.next_action_at ? new Date(row.lead.next_action_at).getTime() : Infinity;
      return [at >= now.getTime() - DAY_MS ? 0 : 3, at];
    }
    case "respondeu":
      return [1, since];
    case "candidatura":
      return [2, since];
    case "visitado":
      return [3, since];
    case "contactado":
      return [4, since]; // oldest first: the longest without an answer
    case "interessa":
      return [5, -new Date(row.card.firstSeen || 0).getTime()];
    case "fechado":
      return [6, since];
    default:
      return [7, -since];
  }
}

export function processRows(
  cards: Card[],
  leads: Map<string, Lead>,
  events: LeadEvent[],
  opts: RowOptions,
  now: Date,
): Row[] {
  const last = new Map<string, LeadEvent>();
  for (const e of events) {
    const prev = last.get(e.group_id);
    if (!prev || e.at > prev.at) last.set(e.group_id, e);
  }
  const rows: Row[] = [];
  for (const card of cards) {
    const stage = stageOf(card, leads);
    if (!stage) continue;
    if (!opts.showFinished && !isActive(stage)) continue;
    if (opts.stage && stage !== opts.stage) continue;
    rows.push({
      card,
      stage,
      lead: leads.get(card.groupId) ?? null,
      lastEvent: last.get(card.groupId) ?? null,
    });
  }
  return rows.sort((a, b) => {
    const [pa, ta] = priority(a, now);
    const [pb, tb] = priority(b, now);
    return pa - pb || ta - tb;
  });
}

export function stageCounts(cards: Card[], leads: Map<string, Lead>): Partial<Record<Stage, number>> {
  const counts: Partial<Record<Stage, number>> = {};
  for (const card of cards) {
    const stage = stageOf(card, leads);
    if (stage) counts[stage] = (counts[stage] ?? 0) + 1;
  }
  return counts;
}

const weekday = new Intl.DateTimeFormat("pt-PT", { weekday: "short" });
const two = (n: number) => String(n).padStart(2, "0");

/** "hoje 18:00", "amanhã 18:00", "sex. 28/11 18:00" */
export function formatWhen(iso: string, now: Date): string {
  const d = new Date(iso);
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(d) - day(now)) / DAY_MS);
  const time = `${two(d.getHours())}:${two(d.getMinutes())}`;
  if (diff === 0) return `hoje ${time}`;
  if (diff === 1) return `amanhã ${time}`;
  return `${weekday.format(d)} ${two(d.getDate())}/${two(d.getMonth() + 1)} ${time}`;
}

export function daysSince(iso: string, now: Date): number {
  return Math.floor((now.getTime() - new Date(iso).getTime()) / DAY_MS);
}

export function nextAction(row: Row, now: Date): string {
  const lead = row.lead;
  switch (row.stage) {
    case "interessa":
      return "Contactar";
    case "contactado": {
      const d = lead ? daysSince(lead.stage_at, now) : 0;
      return d >= 2 ? `Sem resposta há ${d} dias` : "À espera de resposta";
    }
    case "respondeu":
      return "Responder e marcar visita";
    case "visita":
      return lead?.next_action_at ? `Visita ${formatWhen(lead.next_action_at, now)}` : "Marcar data";
    case "visitado":
      return "Decidir: candidatura?";
    case "candidatura":
      return "À espera do senhorio";
    case "fechado":
      return "Contrato fechado";
    default:
      return lead?.reason ?? "—";
  }
}

/** Is the next action overdue or happening soon? (drives the highlight) */
export function isUrgent(row: Row, now: Date): boolean {
  const lead = row.lead;
  if (row.stage === "respondeu") return true;
  if (row.stage === "contactado" && lead) return daysSince(lead.stage_at, now) >= 2;
  if (row.stage === "visita" && lead?.next_action_at) {
    const ms = new Date(lead.next_action_at).getTime() - now.getTime();
    return ms > -DAY_MS && ms < 2 * DAY_MS;
  }
  return false;
}

// --- contacting ---------------------------------------------------------------

/** The message both of you send, in Spanish (portals and agents are Spanish). */
export function contactMessage(card: Card, names: string[]): string {
  const l = card.main;
  const who = names.length > 1 ? `${names.slice(0, -1).join(", ")} y ${names.at(-1)}` : (names[0] ?? "");
  const kind = l.property_type === "house" ? "la casa" : "el piso";
  const where = place(l) ? ` en ${place(l)}` : "";
  return (
    `Hola, somos ${who}. Estamos interesados en ${kind} de ${formatPrice(l.price_eur)}${where} ` +
    `(${l.url}). ¿Sigue disponible? Nos gustaría visitarlo. Muchas gracias.`
  );
}

const EMAIL_RE = /[\w.+-]+@[\w-]+\.[\w.]{2,}/;

export function findEmail(card: Card): string | null {
  for (const l of card.listings) {
    const m = EMAIL_RE.exec(l.description ?? "");
    if (m) return m[0].replace(/[.,;]+$/, "");
  }
  return null;
}

export function mailtoUrl(email: string, card: Card, body: string): string {
  const subject = `Interés en ${card.main.property_type === "house" ? "la casa" : "el piso"} de ${formatPrice(
    card.main.price_eur,
  )}`;
  return `mailto:${email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}
