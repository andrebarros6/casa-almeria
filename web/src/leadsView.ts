// HTML for the lead tracker: contact sheet, lead sheet and the "Em processo" page.
// Every portal- or user-supplied string goes through esc()/safeUrl().

import {
  DISCARD_REASONS,
  DOCUMENTS,
  documentsDone,
  type DocItem,
  isUrgent,
  type Lead,
  type LeadEvent,
  nextAction,
  type Row,
  type Stage,
  STAGE_LABELS,
  STAGES,
} from "./leads";
import { type Card, displayName, esc, facts, formatPrice, place, relativeDay, safeUrl } from "./logic";

export const LEAD_COPY = {
  contact: "Contactar",
  copyAndOpen: "Copiar mensagem e abrir anúncio",
  sendEmail: "Enviar email",
  sent: "Já enviei",
  copied: "Mensagem copiada. Cola-a no formulário do anúncio.",
  copyFailed: "Não consegui copiar. Seleciona o texto e copia à mão.",
  contactHint:
    "Os portais não deixam enviar por aqui: copia a mensagem, abre o anúncio e cola-a no formulário. Depois carrega em “Já enviei”.",
  emptyProcess: "Ainda nada em processo. Dá ❤️ a uma casa ou contacta-a e aparece aqui.",
  emptyStage: "Nenhuma casa nesta fase.",
  addNote: "Adicionar nota",
  visitWhen: "Data da visita",
  reason: "Porquê?",
  backToHomes: "← Casas",
  showFinished: "Mostrar terminados",
};

export function stagePillHtml(stage: Stage | null): string {
  if (!stage) return "";
  return `<span class="stage stage-${stage}">${esc(STAGE_LABELS[stage])}</span>`;
}

// --- contact sheet --------------------------------------------------------------

export function contactSheetHtml(card: Card, message: string, email: string | null): string {
  return `
  <form class="sheet-form" data-form="contact" data-group="${esc(card.groupId)}">
    <h2>${LEAD_COPY.contact}</h2>
    <p class="muted small">${esc(formatPrice(card.main.price_eur))} · ${esc(place(card.main))}</p>
    <p class="hint">${esc(LEAD_COPY.contactHint)}</p>
    <label class="field-label" for="contact-message">Mensagem (podes editar)</label>
    <textarea id="contact-message" name="message" rows="6">${esc(message)}</textarea>
    <div class="sheet-actions stack">
      <button type="button" class="btn-primary" data-action="copy-open"
        data-url="${safeUrl(card.main.url)}">${LEAD_COPY.copyAndOpen}</button>
      ${
        email
          ? `<button type="button" class="btn-ghost" data-action="send-email" data-email="${esc(
              email,
            )}">${LEAD_COPY.sendEmail} (${esc(email)})</button>`
          : ""
      }
      <button type="button" class="btn-ghost" data-action="mark-sent">${LEAD_COPY.sent}</button>
    </div>
  </form>`;
}

// --- lead sheet -----------------------------------------------------------------

function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(
    d.getMinutes(),
  )}`;
}

function eventText(e: LeadEvent, people: Record<string, string>, now: Date): string {
  const who = esc(displayName(e.user_email, people));
  const when = relativeDay(e.at, now);
  const body = esc(e.body ?? "");
  if (e.kind === "stage") return `<b>${who}</b> mudou para <b>${body}</b> · ${when}`;
  if (e.kind === "contact") return `<b>${who}</b> contactou (${body}) · ${when}`;
  return `<b>${who}:</b> ${body} · ${when}`;
}

export function timelineHtml(events: LeadEvent[], people: Record<string, string>, now: Date): string {
  if (!events.length) return `<p class="muted small">Sem histórico ainda.</p>`;
  return `<ol class="timeline">${[...events]
    .sort((a, b) => b.at.localeCompare(a.at))
    .map((e) => `<li>${eventText(e, people, now)}</li>`)
    .join("")}</ol>`;
}

export function leadSheetHtml(
  card: Card,
  stage: Stage | null,
  lead: Lead | null,
  events: LeadEvent[],
  people: Record<string, string>,
  now: Date,
): string {
  const buttons = STAGES.map(
    (s) =>
      `<button type="button" class="stage-btn" data-set-stage="${s.key}" aria-pressed="${
        s.key === stage
      }">${esc(s.label)}</button>`,
  ).join("");
  const visit =
    stage === "visita"
      ? `<label class="field-label" for="visit-at">${LEAD_COPY.visitWhen}</label>
         <input id="visit-at" type="datetime-local" name="visit_at" value="${toLocalInput(
           lead?.next_action_at ?? null,
         )}" data-action="visit-at" />`
      : "";
  const reason =
    stage === "descartado"
      ? `<label class="field-label" for="reason">${LEAD_COPY.reason}</label>
         <select id="reason" name="reason" data-action="reason">
           <option value=""></option>
           ${DISCARD_REASONS.map(
             (r) => `<option ${lead?.reason === r ? "selected" : ""}>${esc(r)}</option>`,
           ).join("")}
         </select>`
      : "";
  return `
  <form class="sheet-form" data-form="lead" data-group="${esc(card.groupId)}">
    <h2>${esc(formatPrice(card.main.price_eur))} · ${esc(place(card.main))}</h2>
    <p class="muted small">${esc(facts(card.main))} · <a href="${safeUrl(
      card.main.url,
    )}" target="_blank" rel="noopener noreferrer">Abrir anúncio →</a></p>
    <fieldset><legend>Fase</legend><div class="stage-grid">${buttons}</div></fieldset>
    ${visit}${reason}
    <label class="field-label" for="lead-note">Nota (ex.: “respondeu, pode visitar sábado”)</label>
    <div class="note-row">
      <input id="lead-note" name="note" autocomplete="off" />
      <button type="submit" class="btn-ghost">${LEAD_COPY.addNote}</button>
    </div>
    <h3 class="section-title">Histórico</h3>
    ${timelineHtml(events, people, now)}
  </form>`;
}

/** Short form for the table: "Bea: pode sábado", "Sam → Contactado", "Sam contactou (portal)". */
export function lastEventText(e: LeadEvent, people: Record<string, string>): string {
  const who = esc(displayName(e.user_email, people));
  const body = esc(e.body ?? "");
  if (e.kind === "stage") return `${who} → ${body}`;
  if (e.kind === "contact") return `${who} contactou (${body})`;
  return `${who}: ${body}`;
}

// --- "Documentos" and "Em processo" pages -----------------------------------------------------------

export function documentsHtml(docs: DocItem[], people: Record<string, string>): string {
  const byKey = new Map(docs.map((d) => [d.key, d]));
  const done = documentsDone(docs);
  const emails = Object.keys(people);
  const items = DOCUMENTS.map((d) => {
    const doc = byKey.get(d.key);
    const link = d.link
      ? ` <a href="${esc(safeUrl(d.link))}" target="_blank" rel="noopener">Abrir →</a>`
      : "";
    const owner = emails.length
      ? `<select data-doc-owner="${esc(d.key)}" aria-label="Quem trata de ${esc(d.label)}">
          <option value="">Quem trata?</option>${emails
            .map(
              (e) =>
                `<option value="${esc(e)}" ${doc?.owner === e ? "selected" : ""}>${esc(
                  displayName(e, people),
                )}</option>`,
            )
            .join("")}
        </select>`
      : "";
    return `<li class="doc">
      <label class="row"><input type="checkbox" data-doc="${esc(d.key)}" ${doc?.ready ? "checked" : ""} /> ${esc(
        d.label,
      )}</label>
      <p class="doc-hint muted">${esc(d.hint)}${link}</p>
      <div class="doc-edit">${owner}<input type="text" data-doc-note="${esc(d.key)}" value="${esc(
        doc?.note ?? "",
      )}" placeholder="Nota (ex.: pedido a 3/12)" aria-label="Nota sobre ${esc(d.label)}" /></div>
    </li>`;
  }).join("");
  return `
  <div class="docs">
    <h2>Documentos para candidatura <span class="muted">${done}/${DOCUMENTS.length} prontos</span></h2>
    <p class="muted small">Para a casa, não por anúncio. Tem tudo em PDF para responder no próprio dia.</p>
    <ul>${items}</ul>
  </div>`;
}

export function stageFilterHtml(
  counts: Partial<Record<Stage, number>>,
  current: Stage | null,
  showFinished: boolean,
): string {
  const visible = STAGES.filter((s) => (s.active || showFinished) && counts[s.key]);
  const chips = visible
    .map(
      (s) =>
        `<button class="qchip" data-stage-filter="${s.key}" aria-pressed="${s.key === current}">${esc(
          s.label,
        )} <span class="tab-count">${counts[s.key]}</span></button>`,
    )
    .join("");
  return `
  <div class="qchips" role="group" aria-label="Filtrar por fase">
    <button class="qchip" data-stage-filter="" aria-pressed="${current === null}">Todas</button>${chips}
  </div>
  <label class="row small"><input type="checkbox" data-action="show-finished" ${
    showFinished ? "checked" : ""
  } /> ${LEAD_COPY.showFinished}</label>`;
}

export function processTableHtml(rows: Row[], people: Record<string, string>, now: Date): string {
  if (!rows.length) return `<p class="empty">${esc(LEAD_COPY.emptyProcess)}</p>`;
  const body = rows
    .map((row) => {
      const l = row.card.main;
      const photo = l.photos[0] ?? row.card.listings.find((x) => x.photos.length)?.photos[0];
      const since = row.lead ? relativeDay(row.lead.stage_at, now) : relativeDay(row.card.firstSeen, now);
      const last = row.lastEvent ? lastEventText(row.lastEvent, people) : "";
      return `
      <tr data-group="${esc(row.card.groupId)}" class="${isUrgent(row, now) ? "urgent" : ""}">
        <th scope="row" class="col-home">
          <button class="row-open" data-action="open-lead">
            ${photo ? `<img src="${safeUrl(photo)}" alt="" loading="lazy" referrerpolicy="no-referrer" />` : ""}
            <span>${esc(place(l) || l.title)}</span>
          </button>
        </th>
        <td><button class="stage-cell" data-action="open-lead">${stagePillHtml(row.stage)}</button></td>
        <td class="next">${esc(nextAction(row, now))}</td>
        <td class="num">${esc(formatPrice(l.price_eur))}</td>
        <td>${esc(facts(l))}</td>
        <td>${esc(since)}</td>
        <td class="last">${last}</td>
        <td>${
          row.stage === "interessa"
            ? `<button class="btn-ghost small" data-action="contact">${LEAD_COPY.contact}</button>`
            : `<a class="btn-link" href="${safeUrl(l.url)}" target="_blank" rel="noopener noreferrer">Anúncio →</a>`
        }</td>
      </tr>`;
    })
    .join("");
  return `
  <div class="table-wrap">
    <table class="process">
      <thead><tr>
        <th scope="col" class="col-home">Casa</th><th scope="col">Fase</th>
        <th scope="col">Próxima ação</th><th scope="col">Preço</th><th scope="col">Quartos</th>
        <th scope="col">Desde</th><th scope="col">Último registo</th><th scope="col"></th>
      </tr></thead>
      <tbody>${body}</tbody>
    </table>
  </div>`;
}
