import { describe, expect, it } from "vitest";
import { buildCards, EMPTY_FILTERS } from "./logic";
import { listing, reaction } from "./test-fixtures";
import {
  cardHtml,
  COPY,
  emptyHtml,
  filterChipsHtml,
  filterSheetHtml,
  healthHtml,
  readFilters,
  tabsHtml,
} from "./view";

const NOW = new Date("2026-11-25T10:00:00Z");
const PEOPLE = { "me@x.pt": "Sam", "p@x.pt": "Bea" };

function dom(html: string): HTMLElement {
  const div = document.createElement("div");
  div.innerHTML = html;
  return div;
}

describe("cardHtml", () => {
  it("renders price, catch, place, chips, sources and reactions", () => {
    const [card] = buildCards(
      [
        listing({
          first_seen: "2026-11-25T07:00:00Z",
          features: ["furnished", "ac", "unknown_feature"],
          price_eur: 800,
          price_history: [
            { at: "a", price_eur: 850 },
            { at: "b", price_eur: 800 },
          ],
        }),
        listing({
          id: "fotocasa:1",
          source: "fotocasa",
          url: "https://www.fotocasa.es/1",
          first_seen: "2026-11-25T08:00:00Z",
        }),
      ],
      [reaction({ user_email: "p@x.pt", note: "gosto da varanda" }), reaction({ user_email: "me@x.pt" })],
    );
    const el = dom(cardHtml(card!, "me@x.pt", PEOPLE, null, NOW));
    expect(el.querySelector(".price")?.textContent).toBe("800 €");
    expect(el.querySelector(".catch")).toBeNull(); // elevator from the other listing, ac present
    expect(el.querySelector(".drop")?.textContent).toBe("baixou 50 €");
    expect(el.querySelector(".place")?.textContent).toContain("Zapillo, Almería");
    expect([...el.querySelectorAll(".chips .chip")].map((c) => c.textContent)).toEqual([
      "elevador",
      "ar cond.",
      "mobilado",
    ]);
    expect(el.querySelectorAll(".sources a")).toHaveLength(2);
    expect(el.querySelector(".badge-new")).not.toBeNull();
    expect(el.querySelector(".react.on-like .who")?.textContent).toBe("BE SA");
    expect(el.querySelector(".note-other")?.textContent).toBe("Bea: gosto da varanda");
    expect(el.querySelector(".card-liked")).not.toBeNull();
    expect(el.querySelector(".photo-count")).toBeNull();
  });

  it("escapes hostile portal text and marks unknown features", () => {
    const [card] = buildCards(
      [
        listing({
          features_known: false,
          features: [],
          neighbourhood: '<script>alert("x")</script>',
          url: "javascript:alert(1)",
          photos: [],
          first_seen: "2026-11-01T00:00:00Z",
        }),
      ],
      [reaction({ user_email: "me@x.pt", reaction: "reject", note: "<b>no</b>" })],
    );
    const html = cardHtml(card!, "me@x.pt", PEOPLE, null, NOW);
    expect(html).not.toContain("<script>");
    const el = dom(html);
    expect(el.querySelector(".catch-unknown")?.getAttribute("title")).toBe(COPY.checkExtrasTip);
    expect(el.querySelector(".btn-link")?.getAttribute("href")).toBe("#");
    expect(el.querySelector(".photo-empty")).not.toBeNull();
    expect(el.querySelector(".badge-new")).toBeNull();
    expect((el.querySelector("textarea") as HTMLTextAreaElement).value).toBe("<b>no</b>");
    expect(el.querySelector(".react.on-reject")).not.toBeNull();
  });

  it("numbers repeat listings from the same portal", () => {
    const [card] = buildCards(
      [listing(), listing({ id: "pisos:2", source_id: "2", url: "https://www.pisos.com/2" })],
      [],
    );
    const el = dom(cardHtml(card!, "me", {}, null, NOW));
    expect([...el.querySelectorAll(".sources a")].map((a) => a.textContent)).toEqual([
      "pisos.com",
      "pisos.com (2)",
    ]);
  });

  it("falls back to another listing's photos and counts them", () => {
    const [card] = buildCards(
      [
        listing({ photos: [] }),
        listing({ id: "x:1", source: "x", features_known: false, photos: ["https://a/1", "https://a/2"] }),
      ],
      [],
    );
    const el = dom(cardHtml(card!, "me", {}, null, NOW));
    expect(el.querySelectorAll(".photo img")).toHaveLength(2);
    expect(el.querySelector(".photo-count")?.textContent).toBe("2 fotos");
  });
});

describe("page parts", () => {
  it("renders tabs with counts and pressed state", () => {
    const el = dom(tabsHtml("liked", { new: 3, all: 40, liked: 2 }));
    const pressed = el.querySelector('[aria-pressed="true"]');
    expect(pressed?.textContent).toBe("Favoritos 2");
    expect(el.querySelectorAll(".tab")).toHaveLength(3);
  });

  it("summarises active filters as chips", () => {
    expect(dom(filterChipsHtml(EMPTY_FILTERS)).textContent).toBe("Filtros");
    const el = dom(
      filterChipsHtml({
        maxPrice: 900,
        minBedrooms: 3,
        areas: ["west_coast", "x"],
        features: ["ac"],
        sources: ["fotocasa"],
        showRejected: true,
      }),
    );
    expect([...el.querySelectorAll(".chip")].map((c) => c.textContent)).toEqual([
      "≤ 900 €",
      "3+ quartos",
      "Poniente",
      "x",
      "ar cond.",
      "Fotocasa",
      "com descartados",
    ]);
    expect(el.querySelector("button")?.textContent).toBe("Filtros (7)");
  });

  it("round-trips the filter sheet through readFilters", () => {
    const filters = {
      maxPrice: 900,
      minBedrooms: 3,
      areas: ["east_coast"],
      features: ["ac", "pool"],
      sources: ["pisos"],
      showRejected: true,
    };
    const el = dom(filterSheetHtml(filters, ["almeria_city", "east_coast"], ["fotocasa", "pisos"]));
    const form = el.querySelector("form") as HTMLFormElement;
    expect(readFilters(form)).toEqual(filters);
    const blank = dom(filterSheetHtml(EMPTY_FILTERS, ["almeria_city"], ["pisos"]));
    expect(readFilters(blank.querySelector("form") as HTMLFormElement)).toEqual(EMPTY_FILTERS);
  });

  it("renders health and empty states", () => {
    expect(healthHtml([])).toBe("");
    const el = dom(healthHtml([{ source: "pisos", state: "ok", label: "pisos.com" }]));
    expect(el.querySelector(".health-ok")?.textContent).toBe("pisos.com");
    expect(emptyHtml("new")).toContain(COPY.emptyNew);
    expect(emptyHtml("liked")).toContain("Ainda sem favoritos");
    expect(emptyHtml("all")).toContain(COPY.emptyAll);
  });

  it("formats messages", () => {
    expect(COPY.linkSent("a@b.pt")).toContain("a@b.pt");
    expect(COPY.deleteNote("Piso", "Bea")).toBe("Apagar a tua nota sobre “Piso”? Bea também deixa de a ver.");
  });
});
