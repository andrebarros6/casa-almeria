// Pure logic for the page: grouping, filtering, sorting and PT-PT formatting.
// No DOM, no network. Everything here is unit-tested.

export interface PricePoint {
  at: string;
  price_eur: number;
}

export interface Listing {
  id: string;
  source: string;
  source_id: string;
  url: string;
  title: string;
  description: string;
  price_eur: number;
  bedrooms: number | null;
  bathrooms: number | null;
  area_m2: number | null;
  floor: number | null;
  property_type: "flat" | "house" | null;
  municipality: string | null;
  neighbourhood: string | null;
  area_key: string | null;
  lat: number | null;
  lng: number | null;
  photos: string[];
  features: string[];
  published_at: string | null;
  is_temporary: boolean;
  /** Only an explicit false means unknown; rows from before this field existed have features. */
  features_known?: boolean;
  first_seen: string | null;
  last_seen: string | null;
  gone: boolean;
  group_id: string | null;
  rejected_reason: string | null;
  price_history: PricePoint[];
  commute_min: number | null;
}

export type ReactionKind = "like" | "reject";

export interface Reaction {
  group_id: string;
  user_email: string;
  reaction: ReactionKind | null;
  note: string | null;
  updated_at: string;
}

export interface SourceRun {
  source: string;
  started_at: string;
  status: "ok" | "blocked" | "error";
  found: number;
  new_matches: number;
}

export interface Card {
  groupId: string;
  main: Listing;
  listings: Listing[];
  sources: string[];
  firstSeen: string;
  priceDrop: number | null;
  features: Set<string>;
  featuresKnown: boolean;
  reactions: Reaction[];
  /** Median of the listings' pins, so one badly geocoded portal can't move the card. */
  point: [number, number] | null;
  /** Estimated walking minutes to work (null when either location is unknown). */
  walkMin: number | null;
}

export type View = "new" | "all" | "liked";

export interface Filters {
  maxPrice: number | null;
  maxWalk: number | null;
  minBedrooms: number | null;
  areas: string[];
  features: string[];
  sources: string[];
  showRejected: boolean;
}

export const EMPTY_FILTERS: Filters = {
  maxPrice: null,
  maxWalk: null,
  minBedrooms: null,
  areas: [],
  features: [],
  sources: [],
  showRejected: false,
};

export const FEATURE_LABELS: Record<string, string> = {
  elevator: "elevador",
  ac: "ar cond.",
  terrace: "terraço",
  balcony: "varanda",
  parking: "garagem",
  pool: "piscina",
  furnished: "mobilado",
  pets: "aceita animais",
  heating: "aquecimento",
  storage: "arrecadação",
};

/** Features offered as filters, in display order. */
export const FILTER_FEATURES = ["elevator", "ac", "terrace", "parking", "furnished", "pets", "pool"];

export const SOURCE_LABELS: Record<string, string> = {
  pisos: "pisos.com",
  enalquiler: "enalquiler",
  fotocasa: "Fotocasa",
  idealista: "Idealista",
  yaencontre: "yaencontre",
  milanuncios: "Milanuncios",
};

export const AREA_LABELS: Record<string, string> = {
  almeria_city: "Almería",
  west_coast: "Poniente",
  east_coast: "Levante",
};

const DAY_MS = 86_400_000;

// --- grouping ---------------------------------------------------------------

export function hasFeatureData(listing: Listing): boolean {
  return listing.features_known !== false;
}

function mainListing(listings: Listing[]): Listing {
  // Prefer listings with feature data, then the one with the most photos.
  return [...listings].sort(
    (a, b) =>
      Number(hasFeatureData(b)) - Number(hasFeatureData(a)) || b.photos.length - a.photos.length,
  )[0] as Listing;
}

function priceDrop(listing: Listing): number {
  const first = listing.price_history[0]?.price_eur;
  return first !== undefined && first > listing.price_eur ? first - listing.price_eur : 0;
}

export function buildCards(
  listings: Listing[],
  reactions: Reaction[],
  work: [number, number] | null = null,
): Card[] {
  const groups = new Map<string, Listing[]>();
  for (const listing of listings) {
    if (listing.gone || listing.rejected_reason) continue;
    const key = listing.group_id ?? listing.id;
    const group = groups.get(key);
    if (group) group.push(listing);
    else groups.set(key, [listing]);
  }
  const reactionsByGroup = new Map<string, Reaction[]>();
  for (const r of reactions) {
    reactionsByGroup.set(r.group_id, [...(reactionsByGroup.get(r.group_id) ?? []), r]);
  }

  const cards: Card[] = [];
  for (const [groupId, group] of groups) {
    const main = mainListing(group);
    const known = group.filter(hasFeatureData);
    const drop = Math.max(...group.map(priceDrop));
    const firstSeen = group
      .map((l) => l.first_seen ?? "")
      .filter(Boolean)
      .sort()[0];
    cards.push({
      groupId,
      main,
      listings: group,
      sources: [...new Set(group.map((l) => l.source))],
      firstSeen: firstSeen ?? "",
      priceDrop: drop > 0 ? drop : null,
      features: new Set(known.flatMap((l) => l.features)),
      featuresKnown: known.length > 0,
      reactions: reactionsByGroup.get(groupId) ?? [],
      point: medianPoint(group),
      walkMin: null,
    });
    const card = cards[cards.length - 1] as Card;
    card.walkMin = work && card.point ? walkMinutes(work, card.point) : null;
  }
  return cards;
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? (sorted[mid] as number) : ((sorted[mid - 1] as number) + (sorted[mid] as number)) / 2;
}

const WALK_DETOUR = 1.3; // streets are ~30% longer than a straight line
const WALK_M_PER_MIN = 5000 / 60; // 5 km/h

function haversineM(a: [number, number], b: [number, number]): number {
  const rad = Math.PI / 180;
  const dLat = (b[0] - a[0]) * rad;
  const dLng = (b[1] - a[1]) * rad;
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * rad) * Math.cos(b[0] * rad) * Math.sin(dLng / 2) ** 2;
  return 2 * 6_371_000 * Math.asin(Math.sqrt(h));
}

/** Straight-line distance x 1.3 at 5 km/h, rounded to whole minutes. */
export function walkMinutes(from: [number, number], to: [number, number]): number {
  return Math.round((haversineM(from, to) * WALK_DETOUR) / WALK_M_PER_MIN);
}

export function medianPoint(listings: Listing[]): [number, number] | null {
  const pins = listings.filter((l) => l.lat !== null && l.lng !== null);
  if (!pins.length) return null;
  return [median(pins.map((l) => l.lat as number)), median(pins.map((l) => l.lng as number))];
}

// --- reactions --------------------------------------------------------------

export function isLiked(card: Card): boolean {
  return card.reactions.some((r) => r.reaction === "like");
}

export function isRejected(card: Card): boolean {
  return card.reactions.some((r) => r.reaction === "reject");
}

export function myReaction(card: Card, me: string): Reaction | undefined {
  return card.reactions.find((r) => r.user_email === me);
}

// --- filtering and sorting --------------------------------------------------

export function isNew(card: Card, lastVisit: string | null, now: Date): boolean {
  const since = lastVisit ?? new Date(now.getTime() - DAY_MS).toISOString();
  return card.firstSeen > since;
}

export function matchesFilters(card: Card, f: Filters): boolean {
  const l = card.main;
  if (f.maxPrice !== null && l.price_eur > f.maxPrice) return false;
  if (f.minBedrooms !== null && (l.bedrooms ?? 0) < f.minBedrooms) return false;
  if (f.maxWalk !== null && (card.walkMin === null || card.walkMin > f.maxWalk)) return false;
  if (f.areas.length && !f.areas.includes(l.area_key ?? "")) return false;
  if (f.sources.length && !card.sources.some((s) => f.sources.includes(s))) return false;
  // A feature filter only passes listings known to have it.
  if (f.features.some((feat) => !card.features.has(feat))) return false;
  return true;
}

export function selectCards(
  cards: Card[],
  view: View,
  filters: Filters,
  lastVisit: string | null,
  now: Date,
): Card[] {
  const picked = cards.filter((card) => {
    if (view === "liked") return isLiked(card);
    if (isRejected(card) && !filters.showRejected) return false;
    if (view === "new" && !isNew(card, lastVisit, now)) return false;
    return matchesFilters(card, filters);
  });
  return sortCards(picked, view);
}

export function sortCards(cards: Card[], view: View): Card[] {
  const newestFirst = (a: Card, b: Card) => b.firstSeen.localeCompare(a.firstSeen);
  if (view !== "all") return [...cards].sort(newestFirst);
  return [...cards].sort((a, b) => {
    const furnished = Number(b.features.has("furnished")) - Number(a.features.has("furnished"));
    if (furnished) return furnished;
    const ca = a.walkMin ?? Infinity;
    const cb = b.walkMin ?? Infinity;
    if (ca !== cb) return ca - cb;
    return newestFirst(a, b);
  });
}

export function countActiveFilters(f: Filters): number {
  return (
    Number(f.maxPrice !== null) +
    Number(f.maxWalk !== null) +
    Number(f.minBedrooms !== null) +
    f.areas.length +
    f.features.length +
    f.sources.length +
    Number(f.showRejected)
  );
}

// --- formatting (PT-PT) -----------------------------------------------------

const euro = new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 0 });

export function formatPrice(eur: number): string {
  return `${euro.format(eur)} €`;
}

export function facts(listing: Listing): string {
  const parts: string[] = [];
  if (listing.bedrooms !== null) {
    parts.push(`${listing.bedrooms} ${listing.bedrooms === 1 ? "quarto" : "quartos"}`);
  }
  if (listing.area_m2 !== null) parts.push(`${listing.area_m2} m²`);
  return parts.join(" · ");
}

/** The catch, stated plainly: what's missing that you'd mention when texting about it. */
export function catchLine(card: Card): string | null {
  if (!card.featuresKnown) return "confirmar extras";
  const missing: string[] = [];
  const isFlat = card.main.property_type !== "house";
  if (isFlat && !card.features.has("elevator")) {
    const floor = card.main.floor;
    missing.push(floor && floor > 0 ? `sem elevador · ${floor}.º andar` : "sem elevador");
  }
  if (!card.features.has("ac")) missing.push("sem ar condicionado");
  return missing.length ? missing.join(" · ") : null;
}

export function place(listing: Listing): string {
  const town = listing.municipality ?? "";
  const hood = listing.neighbourhood?.trim();
  return hood && town && hood !== town ? `${hood}, ${town}` : hood || town;
}

export function relativeDay(iso: string, now: Date): string {
  if (!iso) return "";
  const days = Math.floor((startOfDay(now) - startOfDay(new Date(iso))) / DAY_MS);
  if (days <= 0) return "hoje";
  if (days === 1) return "ontem";
  return `há ${days} dias`;
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** Display name from people map, else a tidy version of the email's local part. */
export function displayName(email: string, people: Record<string, string>): string {
  const known = people[email];
  if (known) return known;
  const local = email.split("@")[0] ?? email;
  const first = local.split(/[._-]/)[0] ?? local;
  return first.charAt(0).toUpperCase() + first.slice(1);
}

export function initials(name: string): string {
  return name.slice(0, 2).toUpperCase();
}

// --- source health ----------------------------------------------------------

export interface SourceHealth {
  source: string;
  state: "ok" | "stale" | "down";
  label: string;
}

export function sourceHealth(runs: SourceRun[], now: Date): SourceHealth[] {
  const latest = new Map<string, SourceRun>();
  const lastOk = new Map<string, SourceRun>();
  for (const run of runs) {
    const prev = latest.get(run.source);
    if (!prev || run.started_at > prev.started_at) latest.set(run.source, run);
    const ok = lastOk.get(run.source);
    if (run.status === "ok" && (!ok || run.started_at > ok.started_at)) lastOk.set(run.source, run);
  }
  return [...latest.values()]
    .sort((a, b) => a.source.localeCompare(b.source))
    .map((run) => {
      const name = SOURCE_LABELS[run.source] ?? run.source;
      const ok = lastOk.get(run.source);
      if (run.status !== "ok") {
        const since = ok ? ` (última vez ${relativeDay(ok.started_at, now)})` : "";
        return { source: run.source, state: "down", label: `${name}: bloqueado${since}` };
      }
      const ageDays = (now.getTime() - new Date(run.started_at).getTime()) / DAY_MS;
      if (ageDays > 1.5) {
        return {
          source: run.source,
          state: "stale",
          label: `${name}: ${relativeDay(run.started_at, now)}`,
        };
      }
      return { source: run.source, state: "ok", label: name };
    });
}

// --- quick chips ------------------------------------------------------------

export interface QuickChip {
  id: string;
  label: string;
}

/** Always-visible one-tap filters. Everything else lives in the Filtros sheet. */
export const QUICK_CHIPS: QuickChip[] = [
  { id: "walk:10", label: "≤ 10 min a pé" },
  { id: "price:900", label: "≤ 900 €" },
  { id: "beds:3", label: "3+ quartos" },
  { id: "feature:furnished", label: "mobilado" },
  { id: "feature:terrace", label: "terraço" },
  { id: "feature:parking", label: "garagem" },
  { id: "feature:pets", label: "animais" },
  { id: "feature:ac", label: "ar cond." },
  { id: "area:almeria_city", label: "Almería" },
  { id: "area:west_coast", label: "Poniente" },
  { id: "area:east_coast", label: "Levante" },
];

export function chipOn(f: Filters, id: string): boolean {
  const [kind, value = ""] = id.split(":");
  if (kind === "walk") return f.maxWalk === Number(value);
  if (kind === "price") return f.maxPrice === Number(value);
  if (kind === "beds") return f.minBedrooms === Number(value);
  if (kind === "feature") return f.features.includes(value);
  if (kind === "area") return f.areas.includes(value);
  return false;
}

const toggleIn = (list: string[], value: string) =>
  list.includes(value) ? list.filter((x) => x !== value) : [...list, value];

export function toggleChip(f: Filters, id: string): Filters {
  const [kind, value = ""] = id.split(":");
  const on = chipOn(f, id);
  if (kind === "walk") return { ...f, maxWalk: on ? null : Number(value) };
  if (kind === "price") return { ...f, maxPrice: on ? null : Number(value) };
  if (kind === "beds") return { ...f, minBedrooms: on ? null : Number(value) };
  if (kind === "feature") return { ...f, features: toggleIn(f.features, value) };
  if (kind === "area") return { ...f, areas: toggleIn(f.areas, value) };
  return f;
}

/** The work location from the latest search summary, if the scraper found it. */
export function workPoint(s: SearchSummary | null): [number, number] | null {
  const c = s?.criteria.commute;
  return c ? [c.lat, c.lng] : null;
}

/** Active filters the chip row doesn't show (they live in the sheet). */
export function hiddenFilterCount(f: Filters): number {
  const shown = QUICK_CHIPS.filter((c) => chipOn(f, c.id)).length;
  return countActiveFilters(f) - shown;
}

// --- search summary ("A procurar") ------------------------------------------

export interface SearchSummary {
  criteria: {
    operation: string;
    max_price_eur: number;
    min_bedrooms: number;
    property_types: string[];
    areas: string[];
    must_have: string;
    excludes: string[];
    commute?: { lat: number; lng: number } | null;
  };
  counts: { seen: number; matching: number; discarded: Record<string, number> };
  updated_at: string;
}

const MUST_HAVE_LABELS: Record<string, string> = {
  elevator_or_ac: "elevador ou ar cond.",
  elevator_and_ac: "elevador e ar cond.",
  ac_plus_elevator_if_above_1st: "ar cond. (e elevador acima do 1.º andar)",
};

export const DISCARD_LABELS: Record<string, string> = {
  short_term: "temporada ou curso escolar",
  price: "acima do preço",
  must_have: "sem elevador nem ar cond.",
  room_share: "quartos partilhados",
  bedrooms: "poucos quartos",
  type: "outro tipo de casa",
  other: "outros motivos",
};

export function criteriaLine(s: SearchSummary): string {
  const c = s.criteria;
  const excludes = c.excludes
    .map((x) => (x === "short_term" ? "temporada" : x === "room_share" ? "quartos partilhados" : x))
    .join(" nem ");
  return [
    "arrendamento longo",
    `até ${formatPrice(c.max_price_eur)}`,
    `${c.min_bedrooms}+ quartos`,
    MUST_HAVE_LABELS[c.must_have] ?? c.must_have,
    c.areas.join(", "),
    excludes ? `sem ${excludes}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Biggest reason first. (Postgres jsonb doesn't keep key order, so sort here.) */
export function discardLines(s: SearchSummary): string[] {
  const order = Object.keys(DISCARD_LABELS);
  const rank = (key: string) => (order.includes(key) ? order.indexOf(key) : order.length);
  return Object.entries(s.counts.discarded)
    .sort(([ka, a], [kb, b]) => b - a || rank(ka) - rank(kb))
    .map(([key, n]) => `${n} ${DISCARD_LABELS[key] ?? key}`);
}

// --- safety -----------------------------------------------------------------

const ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

/** Escape portal-supplied text before putting it in HTML. */
export function esc(text: string | null | undefined): string {
  return (text ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c] ?? c);
}

/** Only allow http(s) URLs from portal data into href/src attributes. */
export function safeUrl(url: string | null | undefined): string {
  return url && /^https?:\/\//i.test(url) ? esc(url) : "#";
}
