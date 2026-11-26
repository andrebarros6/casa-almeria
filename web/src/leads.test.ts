import { describe, expect, it } from "vitest";
import {
  contactMessage,
  daysSince,
  findEmail,
  formatWhen,
  isActive,
  isUrgent,
  type Lead,
  type LeadEvent,
  mailtoUrl,
  nextAction,
  processRows,
  type Row,
  STAGE_LABELS,
  stageCounts,
  stageOf,
} from "./leads";
import { buildCards } from "./logic";
import { listing, reaction } from "./test-fixtures";

const NOW = new Date(2026, 10, 26, 10, 0); // local time, 26 Nov 2026 10:00

function lead(group: string, over: Partial<Lead> = {}): Lead {
  return {
    group_id: group,
    stage: "contactado",
    stage_at: new Date(2026, 10, 25, 9).toISOString(),
    next_action_at: null,
    reason: null,
    updated_by: "me@x.pt",
    updated_at: new Date(2026, 10, 25, 9).toISOString(),
    ...over,
  };
}

const cards = buildCards(
  ["a", "b", "c", "d", "e", "f", "g", "h"].map((id, i) =>
    listing({ id, group_id: id, lat: 36 + i, first_seen: `2026-11-2${i % 6}T07:00:00Z` }),
  ),
  [reaction({ group_id: "a" }), reaction({ group_id: "h" })],
);
const leads = new Map<string, Lead>([
  ["b", lead("b", { stage_at: new Date(2026, 10, 22).toISOString() })], // contacted 4 days ago
  ["c", lead("c", { stage: "respondeu" })],
  ["d", lead("d", { stage: "visita", next_action_at: new Date(2026, 10, 27, 18).toISOString() })],
  ["e", lead("e", { stage: "descartado", reason: "Caro demais" })],
  ["f", lead("f", { stage: "candidatura" })],
  ["g", lead("g", { stage: "contactado" })], // contacted yesterday
]);

describe("stages", () => {
  it("derives stage from lead, or Interessa from a ❤️", () => {
    const byId = (id: string) => cards.find((c) => c.groupId === id)!;
    expect(stageOf(byId("a"), leads)).toBe("interessa");
    expect(stageOf(byId("c"), leads)).toBe("respondeu");
    expect(stageOf(buildCards([listing({ id: "z", group_id: "z" })], [])[0]!, leads)).toBeNull();
    expect(isActive("visita")).toBe(true);
    expect(isActive("descartado")).toBe(false);
    expect(STAGE_LABELS.visita).toBe("Visita marcada");
  });

  it("counts cards per stage", () => {
    expect(stageCounts(cards, leads)).toEqual({
      interessa: 2,
      contactado: 2,
      respondeu: 1,
      visita: 1,
      descartado: 1,
      candidatura: 1,
    });
  });
});

describe("Em processo rows", () => {
  const events: LeadEvent[] = [
    { group_id: "c", user_email: "p@x.pt", kind: "note", body: "pode sábado", at: "2026-11-25T10:00:00Z" },
    { group_id: "c", user_email: "me@x.pt", kind: "contact", body: "portal", at: "2026-11-24T10:00:00Z" },
  ];

  it("shows only active stages, most urgent first", () => {
    const rows = processRows(cards, leads, events, { showFinished: false, stage: null }, NOW);
    expect(rows.map((r) => r.card.groupId)).toEqual(["d", "c", "f", "b", "g", "h", "a"]);
    expect(rows.find((r) => r.card.groupId === "c")!.lastEvent!.body).toBe("pode sábado");
  });

  it("can include finished leads and filter by stage", () => {
    const all = processRows(cards, leads, [], { showFinished: true, stage: null }, NOW);
    expect(all.at(-1)!.card.groupId).toBe("e");
    const only = processRows(cards, leads, [], { showFinished: true, stage: "contactado" }, NOW);
    expect(only.map((r) => r.card.groupId)).toEqual(["b", "g"]);
  });

  it("puts past visits after current work, and closed deals near the end", () => {
    const extra = new Map(leads);
    extra.set("a", lead("a", { stage: "visita", next_action_at: new Date(2026, 10, 1).toISOString() }));
    extra.set("h", lead("h", { stage: "fechado" }));
    const ids = processRows(cards, extra, [], { showFinished: false, stage: null }, NOW).map(
      (r) => r.card.groupId,
    );
    expect(ids.indexOf("a")).toBeGreaterThan(ids.indexOf("c"));
    expect(ids.at(-1)).toBe("h");
    const noDate = new Map([["d", lead("d", { stage: "visita" })]]);
    expect(processRows(cards, noDate, [], { showFinished: false, stage: "visita" }, NOW)).toHaveLength(1);
  });
});

describe("next action and urgency", () => {
  const row = (stage: Row["stage"], l: Lead | null): Row => ({
    card: cards[0]!,
    stage,
    lead: l,
    lastEvent: null,
  });

  it("phrases the next step", () => {
    expect(nextAction(row("interessa", null), NOW)).toBe("Contactar");
    expect(nextAction(row("contactado", leads.get("b")!), NOW)).toBe("Sem resposta há 4 dias");
    expect(nextAction(row("contactado", leads.get("g")!), NOW)).toBe("À espera de resposta");
    expect(nextAction(row("contactado", null), NOW)).toBe("À espera de resposta");
    expect(nextAction(row("respondeu", null), NOW)).toBe("Responder e marcar visita");
    expect(nextAction(row("visita", leads.get("d")!), NOW)).toBe("Visita amanhã 18:00");
    expect(nextAction(row("visita", null), NOW)).toBe("Marcar data");
    expect(nextAction(row("visitado", null), NOW)).toBe("Decidir: candidatura?");
    expect(nextAction(row("candidatura", null), NOW)).toBe("À espera do senhorio");
    expect(nextAction(row("fechado", null), NOW)).toBe("Contrato fechado");
    expect(nextAction(row("descartado", leads.get("e")!), NOW)).toBe("Caro demais");
    expect(nextAction(row("ja_alugado", null), NOW)).toBe("—");
  });

  it("flags what needs attention", () => {
    expect(isUrgent(row("respondeu", null), NOW)).toBe(true);
    expect(isUrgent(row("contactado", leads.get("b")!), NOW)).toBe(true);
    expect(isUrgent(row("contactado", leads.get("g")!), NOW)).toBe(false);
    expect(isUrgent(row("visita", leads.get("d")!), NOW)).toBe(true);
    expect(isUrgent(row("visita", lead("x", { stage: "visita", next_action_at: new Date(2026, 11, 20).toISOString() })), NOW)).toBe(false);
    expect(isUrgent(row("interessa", null), NOW)).toBe(false);
  });

  it("formats dates relative to today", () => {
    expect(formatWhen(new Date(2026, 10, 26, 18, 5).toISOString(), NOW)).toBe("hoje 18:05");
    expect(formatWhen(new Date(2026, 10, 27, 9, 0).toISOString(), NOW)).toBe("amanhã 09:00");
    expect(formatWhen(new Date(2026, 10, 28, 18, 30).toISOString(), NOW)).toMatch(/28\/11 18:30$/);
    expect(daysSince(new Date(2026, 10, 23, 10).toISOString(), NOW)).toBe(3);
  });
});

describe("contact message", () => {
  const [card] = buildCards(
    [
      listing({
        price_eur: 850,
        url: "https://www.pisos.com/x/",
        description: "Contacto: agencia.sol@example.es.",
      }),
    ],
    [],
  );

  it("is written in Spanish from both of you", () => {
    expect(contactMessage(card!, ["André", "Bea"])).toBe(
      "Hola, somos André y Bea. Estamos interesados en el piso de 850 € en Zapillo, Almería " +
        "(https://www.pisos.com/x/). ¿Sigue disponible? Nos gustaría visitarlo. Muchas gracias.",
    );
    expect(contactMessage(card!, ["A", "B", "C"])).toContain("somos A, B y C.");
    const [house] = buildCards([listing({ property_type: "house", neighbourhood: null, municipality: null })], []);
    expect(contactMessage(house!, ["A"])).toContain("somos A. Estamos interesados en la casa de 850 € (");
  });

  it("finds an email in the listing text and builds a mailto link", () => {
    expect(findEmail(card!)).toBe("agencia.sol@example.es");
    expect(findEmail(buildCards([listing()], [])[0]!)).toBeNull();
    const url = mailtoUrl("a@b.es", card!, "Hola & adiós");
    expect(url.startsWith("mailto:a@b.es?subject=Inter%C3%A9s%20en%20el%20piso")).toBe(true);
    expect(url).toContain("body=Hola%20%26%20adi%C3%B3s");
    expect(mailtoUrl("a@b.es", buildCards([listing({ property_type: "house" })], [])[0]!, "x")).toContain(
      "la%20casa",
    );
  });
});
