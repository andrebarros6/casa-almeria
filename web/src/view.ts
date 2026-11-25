// HTML rendering. Every portal-supplied string goes through esc()/safeUrl().

import {
  AREA_LABELS,
  type Card,
  catchLine,
  countActiveFilters,
  displayName,
  esc,
  facts,
  FEATURE_LABELS,
  FILTER_FEATURES,
  type Filters,
  formatPrice,
  initials,
  isNew,
  myReaction,
  place,
  relativeDay,
  safeUrl,
  SOURCE_LABELS,
  type SourceHealth,
  type View,
} from "./logic";

export const COPY = {
  loginTitle: "Casa Almería",
  loginHint: "Entra com o teu email. Mandamos-te um link.",
  sendLink: "Enviar link de entrada",
  linkSent: (email: string) => `Link enviado para ${email}. Abre-o neste telemóvel.`,
  notAllowed: "Esse email não está na lista. Usa o email que combinámos.",
  loading: "A juntar os anúncios…",
  loadError:
    "Não consegui carregar os anúncios. Falhou a ligação ao servidor. Tenta outra vez daqui a um minuto.",
  saveError: "Não consegui guardar. Verifica a ligação e tenta outra vez.",
  emptyNew: "Nada de novo desde ontem. Os portais voltam a ser lidos amanhã de manhã.",
  emptyLiked: "Ainda sem favoritos. Carrega no ❤️ e fica aqui para os dois.",
  emptyAll: "Nenhum anúncio com estes filtros. Tira um ou dois e vê de novo.",
  openListing: "Abrir anúncio",
  checkExtrasTip:
    "Veio de um alerta por email: não sabemos se tem elevador ou ar condicionado. Vê no anúncio.",
  deleteNote: (title: string, partner: string) =>
    `Apagar a tua nota sobre “${title}”? ${partner} também deixa de a ver.`,
  preview: "Pré-visualização com dados locais. Os ❤️ ficam só neste browser.",
};

const VIEW_LABELS: Record<View, string> = { new: "Novos", all: "Todos", liked: "Favoritos" };

export function tabsHtml(view: View, counts: Record<View, number>): string {
  return (["new", "all", "liked"] as View[])
    .map(
      (v) =>
        `<button class="tab" data-view="${v}" aria-pressed="${v === view}">${VIEW_LABELS[v]}` +
        ` <span class="tab-count">${counts[v]}</span></button>`,
    )
    .join("");
}

export function filterChipsHtml(f: Filters): string {
  const chips: string[] = [];
  if (f.maxPrice !== null) chips.push(`≤ ${formatPrice(f.maxPrice)}`);
  if (f.minBedrooms !== null) chips.push(`${f.minBedrooms}+ quartos`);
  chips.push(...f.areas.map((a) => AREA_LABELS[a] ?? a));
  chips.push(...f.features.map((x) => FEATURE_LABELS[x] ?? x));
  chips.push(...f.sources.map((s) => SOURCE_LABELS[s] ?? s));
  if (f.showRejected) chips.push("com descartados");
  const n = countActiveFilters(f);
  return (
    `<button class="btn-ghost" data-action="open-filters">Filtros${n ? ` (${n})` : ""}</button>` +
    chips.map((c) => `<span class="chip chip-active">${esc(c)}</span>`).join("")
  );
}

function photosHtml(card: Card): string {
  const photos = card.main.photos.length
    ? card.main.photos
    : (card.listings.find((l) => l.photos.length)?.photos ?? []);
  if (!photos.length) return `<div class="photo photo-empty">sem fotos</div>`;
  const imgs = photos
    .slice(0, 12)
    .map(
      (src, i) =>
        `<img src="${safeUrl(src)}" alt="" loading="${i === 0 ? "eager" : "lazy"}" referrerpolicy="no-referrer" />`,
    )
    .join("");
  const count = photos.length > 1 ? `<span class="photo-count">${photos.length} fotos</span>` : "";
  return `<div class="photo">${imgs}</div>${count}`;
}

function reactionsHtml(card: Card, me: string, people: Record<string, string>): string {
  const mine = myReaction(card, me);
  const likedBy = card.reactions
    .filter((r) => r.reaction === "like")
    .map((r) => initials(displayName(r.user_email, people)));
  const notes = card.reactions
    .filter((r) => r.note && r.user_email !== me)
    .map(
      (r) =>
        `<p class="note-other"><b>${esc(displayName(r.user_email, people))}:</b> ${esc(r.note)}</p>`,
    )
    .join("");
  return `
    <div class="actions">
      <button class="react ${mine?.reaction === "like" ? "on-like" : ""}" data-action="like"
        aria-pressed="${mine?.reaction === "like"}" aria-label="Gosto">❤️${
          likedBy.length ? `<span class="who">${esc(likedBy.join(" "))}</span>` : ""
        }</button>
      <button class="react ${mine?.reaction === "reject" ? "on-reject" : ""}" data-action="reject"
        aria-pressed="${mine?.reaction === "reject"}" aria-label="Descartar">❌</button>
      <a class="btn-link" href="${safeUrl(card.main.url)}" target="_blank" rel="noopener noreferrer">${
        COPY.openListing
      } →</a>
    </div>
    ${notes}
    <textarea class="note" data-action="note" rows="1" placeholder="nota…"
      aria-label="A tua nota">${esc(mine?.note ?? "")}</textarea>`;
}

export function cardHtml(
  card: Card,
  me: string,
  people: Record<string, string>,
  lastVisit: string | null,
  now: Date,
): string {
  const l = card.main;
  const catchText = catchLine(card);
  const unknown = !card.featuresKnown;
  const featureChips = [...card.features]
    .filter((f) => FEATURE_LABELS[f])
    .sort((a, b) => FILTER_FEATURES.indexOf(a) - FILTER_FEATURES.indexOf(b))
    .map((f) => `<span class="chip">${FEATURE_LABELS[f]}</span>`)
    .join("");
  // One link per listing; a portal that lists the same flat twice reads "Fotocasa (2)".
  const seen = new Map<string, number>();
  const sources = card.listings
    .map((x) => {
      const n = (seen.get(x.source) ?? 0) + 1;
      seen.set(x.source, n);
      const name = SOURCE_LABELS[x.source] ?? x.source;
      return `<a href="${safeUrl(x.url)}" target="_blank" rel="noopener noreferrer">${esc(
        n > 1 ? `${name} (${n})` : name,
      )}</a>`;
    })
    .join(" · ");
  return `
  <article class="card ${myReaction(card, me)?.reaction === "like" ? "card-liked" : ""}" data-group="${esc(
    card.groupId,
  )}">
    <div class="photo-wrap">${photosHtml(card)}${
      isNew(card, lastVisit, now) ? `<span class="badge-new">novo</span>` : ""
    }</div>
    <div class="body">
      <p class="price-line"><span class="price">${formatPrice(l.price_eur)}</span>
        <span class="facts">${esc(facts(l))}</span></p>
      ${
        catchText
          ? `<p class="catch ${unknown ? "catch-unknown" : ""}"${
              unknown ? ` title="${esc(COPY.checkExtrasTip)}"` : ""
            }>${esc(catchText)}</p>`
          : ""
      }
      ${card.priceDrop ? `<p class="drop">baixou ${formatPrice(card.priceDrop)}</p>` : ""}
      <p class="place">${esc(place(l))} · <span class="muted">${relativeDay(card.firstSeen, now)}</span></p>
      ${featureChips ? `<div class="chips">${featureChips}</div>` : ""}
      <p class="sources">${sources}</p>
      ${reactionsHtml(card, me, people)}
    </div>
  </article>`;
}

export function healthHtml(health: SourceHealth[]): string {
  if (!health.length) return "";
  return (
    `<span class="muted">Fontes:</span> ` +
    health
      .map((h) => `<span class="health health-${h.state}">${esc(h.label)}</span>`)
      .join(" · ")
  );
}

export function emptyHtml(view: View): string {
  const text = view === "new" ? COPY.emptyNew : view === "liked" ? COPY.emptyLiked : COPY.emptyAll;
  return `<p class="empty">${esc(text)}</p>`;
}

export function filterSheetHtml(f: Filters, areas: string[], sources: string[]): string {
  const check = (name: string, value: string, label: string, on: boolean) =>
    `<label class="chip chip-toggle"><input type="checkbox" name="${name}" value="${esc(value)}" ${
      on ? "checked" : ""
    } /> ${esc(label)}</label>`;
  return `
  <form class="sheet-form" data-form="filters">
    <h2>Filtros</h2>
    <fieldset><legend>Renda até</legend>
      <select name="maxPrice">
        <option value="">qualquer</option>
        ${[700, 800, 900, 1000]
          .map(
            (p) =>
              `<option value="${p}" ${f.maxPrice === p ? "selected" : ""}>${formatPrice(p)}</option>`,
          )
          .join("")}
      </select>
    </fieldset>
    <fieldset><legend>Quartos</legend>
      <select name="minBedrooms">
        <option value="">2+</option>
        ${[3, 4]
          .map((n) => `<option value="${n}" ${f.minBedrooms === n ? "selected" : ""}>${n}+</option>`)
          .join("")}
      </select>
    </fieldset>
    <fieldset><legend>Zona</legend><div class="chips">
      ${areas.map((a) => check("areas", a, AREA_LABELS[a] ?? a, f.areas.includes(a))).join("")}
    </div></fieldset>
    <fieldset><legend>Tem de ter</legend><div class="chips">
      ${FILTER_FEATURES.map((x) =>
        check("features", x, FEATURE_LABELS[x] ?? x, f.features.includes(x)),
      ).join("")}
    </div></fieldset>
    <fieldset><legend>Portal</legend><div class="chips">
      ${sources.map((s) => check("sources", s, SOURCE_LABELS[s] ?? s, f.sources.includes(s))).join("")}
    </div></fieldset>
    <label class="row"><input type="checkbox" name="showRejected" ${
      f.showRejected ? "checked" : ""
    } /> Mostrar descartados</label>
    <div class="sheet-actions">
      <button type="button" class="btn-ghost" data-action="clear-filters">Limpar filtros</button>
      <button type="submit" class="btn-primary">Ver anúncios</button>
    </div>
  </form>`;
}

export function readFilters(form: HTMLFormElement): Filters {
  const data = new FormData(form);
  const num = (key: string) => {
    const v = data.get(key);
    return v ? Number(v) : null;
  };
  return {
    maxPrice: num("maxPrice"),
    minBedrooms: num("minBedrooms"),
    areas: data.getAll("areas").map(String),
    features: data.getAll("features").map(String),
    sources: data.getAll("sources").map(String),
    showRejected: data.get("showRejected") !== null,
  };
}
