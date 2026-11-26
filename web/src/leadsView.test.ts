import { describe, expect, it } from "vitest";
import { documentsDone, type Lead, type LeadEvent, type Row } from "./leads";
import {
  contactSheetHtml,
  documentsHtml,
  LEAD_COPY,
  lastEventText,
  leadSheetHtml,
  processTableHtml,
  stageFilterHtml,
  stagePillHtml,
  timelineHtml,
} from "./leadsView";
import { buildCards } from "./logic";
import { listing } from "./test-fixtures";
import { cardHtml } from "./view";

const NOW = new Date(2026, 10, 26, 10, 0);
const PEOPLE = { "me@x.pt": "Sam", "p@x.pt": "Bea" };
const [CARD] = buildCards([listing({ neighbourhood: "<b>Zapillo</b>" })], []);

function dom(html: string): HTMLElement {
  const div = document.createElement("div");
  div.innerHTML = html;
  return div;
}

const LEAD: Lead = {
  group_id: "pisos:1",
  stage: "visita",
  stage_at: new Date(2026, 10, 25).toISOString(),
  next_action_at: new Date(2026, 10, 27, 18, 0).toISOString(),
  reason: null,
  updated_by: "me@x.pt",
  updated_at: new Date(2026, 10, 25).toISOString(),
};

describe("contact sheet", () => {
  it("shows the editable message, copy+open, mark-sent and email only when known", () => {
    const el = dom(contactSheetHtml(CARD!, "Hola <x>", null));
    expect((el.querySelector("textarea") as HTMLTextAreaElement).value).toBe("Hola <x>");
    expect(el.querySelector("[data-action=copy-open]")?.getAttribute("data-url")).toBe(CARD!.main.url);
    expect(el.querySelector("[data-action=mark-sent]")).not.toBeNull();
    expect(el.querySelector("[data-action=send-email]")).toBeNull();
    expect(el.innerHTML).not.toContain("<b>Zapillo</b>");
    const withEmail = dom(contactSheetHtml(CARD!, "x", "a@b.es"));
    expect(withEmail.querySelector("[data-action=send-email]")?.textContent).toContain("a@b.es");
  });
});

describe("lead sheet", () => {
  const events: LeadEvent[] = [
    { group_id: "pisos:1", user_email: "me@x.pt", kind: "contact", body: "portal", at: "2026-11-24T10:00:00Z" },
    { group_id: "pisos:1", user_email: "p@x.pt", kind: "note", body: "<i>pode sábado</i>", at: "2026-11-25T10:00:00Z" },
    { group_id: "pisos:1", user_email: "p@x.pt", kind: "stage", body: "Visita marcada", at: "2026-11-25T11:00:00Z" },
  ];

  it("shows stages, visit date for visits, and the timeline newest first", () => {
    const el = dom(leadSheetHtml(CARD!, "visita", LEAD, events, PEOPLE, NOW));
    expect(el.querySelector('[aria-pressed="true"]')?.textContent).toBe("Visita marcada");
    expect(el.querySelectorAll("[data-set-stage]")).toHaveLength(10);
    expect((el.querySelector("#visit-at") as HTMLInputElement).value).toBe("2026-11-27T18:00");
    expect(el.querySelector("#reason")).toBeNull();
    const items = [...el.querySelectorAll(".timeline li")].map((li) => li.textContent);
    expect(items[0]).toContain("Bea mudou para Visita marcada");
    expect(items[1]).toContain("Bea: <i>pode sábado</i>");
    expect(items[2]).toContain("Sam contactou (portal)");
  });

  it("asks why when discarded", () => {
    const el = dom(leadSheetHtml(CARD!, "descartado", { ...LEAD, stage: "descartado", reason: "Zona" }, [], PEOPLE, NOW));
    expect((el.querySelector("#reason") as HTMLSelectElement).value).toBe("Zona");
    expect(el.querySelector("#visit-at")).toBeNull();
    expect(el.textContent).toContain("Sem histórico ainda.");
    const blankVisit = dom(leadSheetHtml(CARD!, "visita", null, [], PEOPLE, NOW));
    expect((blankVisit.querySelector("#visit-at") as HTMLInputElement).value).toBe("");
  });

  it("phrases the latest event for the table", () => {
    const e = { group_id: "g", user_email: "me@x.pt", at: "x" };
    expect(lastEventText({ ...e, kind: "stage", body: "Contactado" }, PEOPLE)).toBe("Sam → Contactado");
    expect(lastEventText({ ...e, kind: "contact", body: "portal" }, PEOPLE)).toBe("Sam contactou (portal)");
    expect(lastEventText({ ...e, kind: "note", body: "<b>x</b>" }, PEOPLE)).toBe("Sam: &lt;b&gt;x&lt;/b&gt;");
    expect(lastEventText({ ...e, kind: "note", body: null }, PEOPLE)).toBe("Sam: ");
  });

  it("timeline helper handles empty lists", () => {
    expect(timelineHtml([], PEOPLE, NOW)).toContain("Sem histórico");
  });
});

describe("Em processo page", () => {
  it("renders the documents checklist with progress", () => {
    const el = dom(documentsHtml([{ key: "dni_nie", ready: true, note: null }], PEOPLE));
    expect(el.querySelector("h2")?.textContent).toContain("1/7 prontos");
    expect((el.querySelector('[data-doc="dni_nie"]') as HTMLInputElement).checked).toBe(true);
    expect((el.querySelector('[data-doc="aval"]') as HTMLInputElement).checked).toBe(false);
  });

  it("shows how to get each document, its owner and note", () => {
    const [email] = Object.keys(PEOPLE);
    const docs = [{ key: "renta", ready: false, note: "<pedido>", owner: email }];
    const el = dom(documentsHtml(docs, PEOPLE));
    const item = el.querySelector('[data-doc="renta"]')?.closest("li") as HTMLElement;
    expect(item.textContent).toContain("Portal das Finanças");
    expect(item.querySelector("a")?.getAttribute("href")).toMatch(/^https:\/\//);
    expect((item.querySelector("[data-doc-owner]") as HTMLSelectElement).value).toBe(email);
    expect((item.querySelector("[data-doc-note]") as HTMLInputElement).value).toBe("<pedido>");
    expect(el.innerHTML).not.toContain("<pedido>");
  });

  it("counts only known documents that are ready", () => {
    const docs = [
      { key: "nominas", ready: true, note: null },
      { key: "fianza", ready: false, note: null },
      { key: "old_key", ready: true, note: null },
    ];
    expect(documentsDone(docs)).toBe(1);
  });

  it("hides the owner picker when nobody is known (preview mode)", () => {
    const el = dom(documentsHtml([], {}));
    expect(el.querySelector("[data-doc-owner]")).toBeNull();
    expect(el.querySelectorAll("[data-doc-note]").length).toBe(7);
  });

  it("renders stage chips with counts, hiding finished unless asked", () => {
    const counts = { interessa: 2, contactado: 1, descartado: 3 };
    const el = dom(stageFilterHtml(counts, "contactado", false));
    expect([...el.querySelectorAll("[data-stage-filter]")].map((b) => b.textContent?.trim())).toEqual([
      "Todas",
      "Interessa 2",
      "Contactado 1",
    ]);
    expect(el.querySelector('[aria-pressed="true"]')?.textContent).toContain("Contactado");
    const withFinished = dom(stageFilterHtml(counts, null, true));
    expect(withFinished.textContent).toContain("Descartado");
    expect((withFinished.querySelector("[data-action=show-finished]") as HTMLInputElement).checked).toBe(true);
  });

  it("renders table rows with next action, urgency and actions", () => {
    const rows: Row[] = [
      { card: CARD!, stage: "visita", lead: LEAD, lastEvent: { group_id: "pisos:1", user_email: "p@x.pt", kind: "note", body: "ok", at: "x" } },
      { card: CARD!, stage: "interessa", lead: null, lastEvent: null },
    ];
    const el = dom(processTableHtml(rows, PEOPLE, NOW));
    const trs = el.querySelectorAll("tbody tr");
    expect(trs).toHaveLength(2);
    expect(trs[0]!.classList.contains("urgent")).toBe(true);
    expect(trs[0]!.querySelector(".next")?.textContent).toBe("Visita amanhã 18:00");
    expect(trs[0]!.querySelector(".last")?.textContent).toBe("Bea: ok");
    expect(trs[0]!.querySelector(".stage")?.textContent).toBe("Visita marcada");
    expect(trs[1]!.querySelector("[data-action=contact]")).not.toBeNull();
    expect(el.innerHTML).not.toContain("<b>Zapillo</b>");
    expect(processTableHtml([], PEOPLE, NOW)).toContain(LEAD_COPY.emptyProcess);
  });
});

describe("cards", () => {
  it("show Contactar until a lead exists, then the stage", () => {
    expect(dom(cardHtml(CARD!, "me", {}, null, NOW)).querySelector("[data-action=contact]")).not.toBeNull();
    expect(dom(cardHtml(CARD!, "me", {}, null, NOW, "interessa")).querySelector("[data-action=contact]")).not.toBeNull();
    const el = dom(cardHtml(CARD!, "me", {}, null, NOW, "respondeu"));
    expect(el.querySelector("[data-action=open-lead] .stage")?.textContent).toBe("Respondeu");
    expect(stagePillHtml(null)).toBe("");
  });
});
