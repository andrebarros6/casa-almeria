import { describe, expect, it } from "vitest";
import {
  buildCards,
  catchLine,
  chipOn,
  criteriaLine,
  discardLines,
  countActiveFilters,
  displayName,
  EMPTY_FILTERS,
  esc,
  facts,
  type Filters,
  formatPrice,
  hiddenFilterCount,
  initials,
  isLiked,
  isNew,
  isRejected,
  type Listing,
  matchesFilters,
  medianPoint,
  myReaction,
  place,
  QUICK_CHIPS,
  relativeDay,
  type SearchSummary,
  safeUrl,
  selectCards,
  sortCards,
  sourceHealth,
  toggleChip,
  walkMinutes,
  workPoint,
} from "./logic";
import { listing, reaction } from "./test-fixtures";

const NOW = new Date("2026-11-25T10:00:00Z");

describe("buildCards", () => {
  it("groups duplicates, prefers listings with features, merges data", () => {
    const cards = buildCards(
      [
        listing({ id: "idealista:9", source: "idealista", features_known: false, features: [], photos: [] }),
        listing({
          id: "fotocasa:2",
          source: "fotocasa",
          photos: ["a", "b"],
          features: ["furnished"],
          first_seen: "2026-11-20T07:00:00Z",
          price_eur: 800,
          price_history: [
            { at: "2026-11-20T07:00:00Z", price_eur: 900 },
            { at: "2026-11-24T07:00:00Z", price_eur: 800 },
          ],
        }),
        listing(),
        listing({ id: "pisos:gone", group_id: "pisos:gone", gone: true }),
        listing({ id: "pisos:rej", group_id: "pisos:rej", rejected_reason: "price" }),
        listing({ id: "solo", group_id: null }),
      ],
      [reaction(), reaction({ group_id: "solo", user_email: "b@x.pt", reaction: "reject" })],
    );
    expect(cards.map((c) => c.groupId).sort()).toEqual(["pisos:1", "solo"]);
    const card = cards.find((c) => c.groupId === "pisos:1")!;
    expect(card.main.id).toBe("fotocasa:2");
    expect(card.sources.sort()).toEqual(["fotocasa", "idealista", "pisos"]);
    expect([...card.features].sort()).toEqual(["ac", "elevator", "furnished"]);
    expect(card.featuresKnown).toBe(true);
    expect(card.firstSeen).toBe("2026-11-20T07:00:00Z");
    expect(card.priceDrop).toBe(100);
    expect(isLiked(card)).toBe(true);
    expect(isRejected(cards.find((c) => c.groupId === "solo")!)).toBe(true);
  });

  it("marks email-only groups as features unknown and no price drop", () => {
    const [card] = buildCards([listing({ features_known: false, features: [], first_seen: null })], []);
    expect(card!.featuresKnown).toBe(false);
    expect(card!.priceDrop).toBeNull();
    expect(card!.firstSeen).toBe("");
  });
});

describe("selection", () => {
  const cards = buildCards(
    [
      listing({ id: "a", group_id: "a", first_seen: "2026-11-25T07:00:00Z", features: ["ac"] }),
      listing({
        id: "b",
        group_id: "b",
        first_seen: "2026-11-10T07:00:00Z",
        price_eur: 990,
        area_key: "west_coast",
        features: ["furnished", "ac"],
        source: "fotocasa",
      }),
      listing({ id: "c", group_id: "c", first_seen: "2026-11-24T20:00:00Z", lat: 36.8425 }),
      listing({ id: "d", group_id: "d", first_seen: "2026-11-24T21:00:00Z", lat: 36.842 }),
    ],
    [reaction({ group_id: "c", reaction: "reject" }), reaction({ group_id: "b" })],
    [36.842, -2.44], // work: d is 0 min away, c 1 min, a ~3 min
  );

  it("new view uses last visit, or the last 24h when there is none", () => {
    const sinceYesterday = selectCards(cards, "new", EMPTY_FILTERS, null, NOW);
    expect(sinceYesterday.map((c) => c.groupId)).toEqual(["a", "d"]); // c rejected, b old
    const sinceLastVisit = selectCards(cards, "new", EMPTY_FILTERS, "2026-11-24T22:00:00Z", NOW);
    expect(sinceLastVisit.map((c) => c.groupId)).toEqual(["a"]);
    expect(isNew(cards[0]!, null, NOW)).toBe(true);
  });

  it("all view hides rejected unless asked and sorts furnished, commute, newest", () => {
    expect(selectCards(cards, "all", EMPTY_FILTERS, null, NOW).map((c) => c.groupId)).toEqual([
      "b",
      "d",
      "a",
    ]);
    const withRejected = { ...EMPTY_FILTERS, showRejected: true };
    expect(selectCards(cards, "all", withRejected, null, NOW).map((c) => c.groupId)).toEqual([
      "b",
      "d",
      "c",
      "a",
    ]);
  });

  it("liked view shows liked cards regardless of filters", () => {
    const strict = { ...EMPTY_FILTERS, maxPrice: 500 };
    expect(selectCards(cards, "liked", strict, null, NOW).map((c) => c.groupId)).toEqual(["b"]);
  });

  it("filters by price, bedrooms, area, source and features", () => {
    const card = cards.find((c) => c.groupId === "b")!;
    const f = (over: Partial<Filters>) => matchesFilters(card, { ...EMPTY_FILTERS, ...over });
    expect(f({})).toBe(true);
    expect(f({ maxPrice: 900 })).toBe(false);
    expect(f({ minBedrooms: 4 })).toBe(false);
    expect(f({ areas: ["east_coast"] })).toBe(false);
    expect(f({ areas: ["west_coast"] })).toBe(true);
    expect(f({ sources: ["pisos"] })).toBe(false);
    expect(f({ sources: ["fotocasa"] })).toBe(true);
    expect(f({ features: ["furnished"] })).toBe(true);
    expect(f({ features: ["pool"] })).toBe(false);
    const noBedrooms = buildCards([listing({ bedrooms: null })], [])[0]!;
    expect(matchesFilters(noBedrooms, { ...EMPTY_FILTERS, minBedrooms: 2 })).toBe(false);
  });

  it("sortCards keeps newest first outside the all view", () => {
    expect(sortCards(cards, "liked").map((c) => c.groupId)).toEqual(["a", "d", "c", "b"]);
  });

  it("counts active filters", () => {
    expect(countActiveFilters(EMPTY_FILTERS)).toBe(0);
    expect(
      countActiveFilters({
        maxPrice: 900,
        maxWalk: 10,
        minBedrooms: 3,
        areas: ["a", "b"],
        features: ["ac"],
        sources: ["pisos"],
        showRejected: true,
      }),
    ).toBe(8);
  });
});

describe("formatting", () => {
  it("formats price and facts in PT-PT", () => {
    expect(formatPrice(850)).toBe("850 €");
    expect(facts(listing())).toBe("3 quartos · 95 m²");
    expect(facts(listing({ bedrooms: 1, area_m2: null }))).toBe("1 quarto");
    expect(facts(listing({ bedrooms: null, area_m2: null }))).toBe("");
  });

  it("states the catch", () => {
    const card = (over: Partial<Listing>) => buildCards([listing(over)], [])[0]!;
    expect(catchLine(card({}))).toBeNull();
    expect(catchLine(card({ features: ["ac"] }))).toBe("sem elevador · 4.º andar");
    expect(catchLine(card({ features: ["ac"], floor: 0 }))).toBe("sem elevador");
    expect(catchLine(card({ features: [] , floor: null}))).toBe("sem elevador · sem ar condicionado");
    expect(catchLine(card({ property_type: "house", features: ["ac"] }))).toBeNull();
    expect(catchLine(card({ features_known: false, features: [] }))).toBe("confirmar extras");
  });

  it("builds place names", () => {
    expect(place(listing())).toBe("Zapillo, Almería");
    expect(place(listing({ neighbourhood: "Almería" }))).toBe("Almería");
    expect(place(listing({ neighbourhood: null }))).toBe("Almería");
    expect(place(listing({ neighbourhood: " ", municipality: null }))).toBe("");
  });

  it("says when, relative to today", () => {
    expect(relativeDay("2026-11-25T08:00:00Z", NOW)).toBe("hoje");
    expect(relativeDay("2026-11-24T08:00:00Z", NOW)).toBe("ontem");
    expect(relativeDay("2026-11-20T08:00:00Z", NOW)).toBe("há 5 dias");
    expect(relativeDay("", NOW)).toBe("");
  });

  it("derives names and initials", () => {
    expect(displayName("sam.rivera@x.pt", {})).toBe("Sam");
    expect(displayName("a@x.pt", { "a@x.pt": "Sam" })).toBe("Sam");
    expect(initials("Sam")).toBe("SA");
  });

  it("finds my reaction", () => {
    const [card] = buildCards([listing()], [reaction(), reaction({ user_email: "b@x.pt" })]);
    expect(myReaction(card!, "b@x.pt")?.user_email).toBe("b@x.pt");
    expect(myReaction(card!, "nobody")).toBeUndefined();
  });
});

describe("source health", () => {
  it("reports ok, stale and blocked sources", () => {
    const health = sourceHealth(
      [
        { source: "pisos", started_at: "2026-11-25T06:00:00Z", status: "ok", found: 1, new_matches: 0 },
        { source: "pisos", started_at: "2026-11-24T06:00:00Z", status: "ok", found: 1, new_matches: 0 },
        { source: "fotocasa", started_at: "2026-11-21T09:00:00Z", status: "ok", found: 1, new_matches: 0 },
        { source: "idealista", started_at: "2026-11-25T06:00:00Z", status: "blocked", found: 0, new_matches: 0 },
        { source: "idealista", started_at: "2026-11-23T06:00:00Z", status: "ok", found: 3, new_matches: 1 },
        { source: "weird", started_at: "2026-11-25T06:00:00Z", status: "error", found: 0, new_matches: 0 },
      ],
      NOW,
    );
    expect(health).toEqual([
      { source: "fotocasa", state: "stale", label: "Fotocasa: há 4 dias" },
      { source: "idealista", state: "down", label: "Idealista: bloqueado (última vez há 2 dias)" },
      { source: "pisos", state: "ok", label: "pisos.com" },
      { source: "weird", state: "down", label: "weird: bloqueado" },
    ]);
  });
});

describe("safety", () => {
  it("escapes HTML and rejects non-http URLs", () => {
    expect(esc(`<img src=x onerror="a">&'`)).toBe("&lt;img src=x onerror=&quot;a&quot;&gt;&amp;&#39;");
    expect(esc(null)).toBe("");
    expect(safeUrl("javascript:alert(1)")).toBe("#");
    expect(safeUrl(null)).toBe("#");
    expect(safeUrl('https://a.test/?q="x"')).toBe("https://a.test/?q=&quot;x&quot;");
  });
});

describe("legacy rows", () => {
  it("treats a missing features_known as known", () => {
    const legacy = listing({ features: ["furnished"] });
    delete legacy.features_known;
    const [card] = buildCards([legacy], []);
    expect(card!.featuresKnown).toBe(true);
    expect(card!.features.has("furnished")).toBe(true);
  });
});

describe("quick chips", () => {
  it("toggles price, bedrooms, features and areas", () => {
    let f = EMPTY_FILTERS;
    for (const id of ["price:900", "beds:3", "feature:terrace", "area:east_coast"]) {
      expect(chipOn(f, id)).toBe(false);
      f = toggleChip(f, id);
      expect(chipOn(f, id)).toBe(true);
    }
    expect(f).toMatchObject({ maxPrice: 900, minBedrooms: 3, features: ["terrace"], areas: ["east_coast"] });
    expect(hiddenFilterCount(f)).toBe(0);
    for (const id of ["price:900", "beds:3", "feature:terrace", "area:east_coast"]) f = toggleChip(f, id);
    expect(f).toEqual(EMPTY_FILTERS);
    expect(toggleChip(f, "bogus:1")).toBe(f);
    expect(chipOn(f, "bogus:1")).toBe(false);
    expect(hiddenFilterCount({ ...EMPTY_FILTERS, maxPrice: 800, showRejected: true })).toBe(2);
    expect(QUICK_CHIPS.every((c) => c.label.length > 0)).toBe(true);
  });
});

describe("median pin", () => {
  it("ignores one badly geocoded portal", () => {
    const pins = [
      listing({ lat: 36.84, lng: -2.46 }),
      listing({ lat: 36.841, lng: -2.461 }),
      listing({ lat: 36.95, lng: -2.3 }), // 12 km off
    ];
    expect(medianPoint(pins)).toEqual([36.841, -2.46]);
    const two = medianPoint(pins.slice(0, 2))!;
    expect(two[0]).toBeCloseTo(36.8405, 6);
    expect(two[1]).toBeCloseTo(-2.4605, 6);
    expect(medianPoint([listing({ lat: null, lng: null })])).toBeNull();
    const [card] = buildCards(pins, []);
    expect(card!.point).toEqual([36.841, -2.46]);
  });
});

describe("search summary text", () => {
  const summary: SearchSummary = {
    criteria: {
      operation: "rent",
      max_price_eur: 1000,
      min_bedrooms: 2,
      property_types: ["flat"],
      areas: ["Almería ciudad"],
      must_have: "ac_plus_elevator_if_above_1st",
      excludes: ["short_term", "room_share", "x"],
    },
    counts: { seen: 3, matching: 1, discarded: { room_share: 1, mystery: 1 } },
    updated_at: "2026-11-25T07:00:00Z",
  };

  it("phrases criteria and discards in PT-PT", () => {
    expect(criteriaLine(summary)).toBe(
      "arrendamento longo · até 1000 € · 2+ quartos · ar cond. (e elevador acima do 1.º andar) · Almería ciudad · sem temporada nem quartos partilhados nem x",
    );
    expect(criteriaLine({ ...summary, criteria: { ...summary.criteria, must_have: "new_rule", excludes: [] } })).toBe(
      "arrendamento longo · até 1000 € · 2+ quartos · new_rule · Almería ciudad",
    );
    expect(discardLines(summary)).toEqual(["1 quartos partilhados", "1 mystery"]);
    const unordered = { ...summary, counts: { ...summary.counts, discarded: { price: 74, bedrooms: 89, short_term: 460 } } };
    expect(discardLines(unordered)).toEqual([
      "460 temporada ou curso escolar",
      "89 poucos quartos",
      "74 acima do preço",
    ]);
  });
});


describe("walking time", () => {
  it("estimates minutes from the straight line x 1.3 at 5 km/h", () => {
    expect(walkMinutes([36.84, -2.46], [36.84, -2.46])).toBe(0);
    // 0.005 deg latitude ~ 556 m -> 723 m walked -> ~9 min
    expect(walkMinutes([36.84, -2.46], [36.845, -2.46])).toBe(9);
  });

  it("filters by maximum walk and needs a known location", () => {
    const near = listing({ id: "n", group_id: "n", lat: 36.841 });
    const far = listing({ id: "f", group_id: "f", lat: 36.86 });
    const cards = buildCards([near, far], [], [36.84, -2.44]);
    const f = { ...EMPTY_FILTERS, maxWalk: 10 };
    expect(cards.filter((c) => matchesFilters(c, f)).map((c) => c.groupId)).toEqual(["n"]);
    const unknown = buildCards([near], [])[0]!;
    expect(unknown.walkMin).toBeNull();
    expect(matchesFilters(unknown, f)).toBe(false);
    expect(chipOn(f, "walk:10")).toBe(true);
    expect(toggleChip(f, "walk:10").maxWalk).toBeNull();
    expect(toggleChip(EMPTY_FILTERS, "walk:10").maxWalk).toBe(10);
  });

  it("reads the work point from the summary", () => {
    expect(workPoint(null)).toBeNull();
    const base = { criteria: { operation: "rent", max_price_eur: 1, min_bedrooms: 1, property_types: [], areas: [], must_have: "", excludes: [] }, counts: { seen: 0, matching: 0, discarded: {} }, updated_at: "" };
    expect(workPoint(base)).toBeNull();
    expect(workPoint({ ...base, criteria: { ...base.criteria, commute: { lat: 1, lng: 2 } } })).toEqual([1, 2]);
  });
});
