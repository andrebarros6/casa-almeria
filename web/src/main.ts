import "./styles.css";
import { type Backend, createBackend, NotAllowedError, type Snapshot } from "./data";
import {
  buildCards,
  type Card,
  displayName,
  EMPTY_FILTERS,
  type Filters,
  isLiked,
  isNew,
  isRejected,
  myReaction,
  type ReactionKind,
  selectCards,
  sourceHealth,
  toggleChip,
  type View,
} from "./logic";
import {
  cardHtml,
  COPY,
  emptyHtml,
  filterChipsHtml,
  filterSheetHtml,
  healthHtml,
  readFilters,
  summaryHtml,
  tabsHtml,
} from "./view";

const app = document.querySelector<HTMLDivElement>("#app") as HTMLDivElement;
const backend: Backend = createBackend();

const state = {
  me: "",
  snapshot: null as Snapshot | null,
  cards: [] as Card[],
  view: "new" as View,
  mode: "list" as "list" | "map",
  filters: loadFilters(),
  lastVisit: null as string | null,
  criteriaOpen: false,
};

function loadFilters(): Filters {
  try {
    return { ...EMPTY_FILTERS, ...JSON.parse(localStorage.getItem("filters") ?? "{}") };
  } catch {
    return { ...EMPTY_FILTERS };
  }
}

/** "Novos" = first seen since the previous visit. Kept stable across reloads in one session. */
function resolveLastVisit(me: string): string | null {
  const key = `lastVisit:${me}`;
  const session = sessionStorage.getItem(key);
  if (session !== null) return session || null;
  const previous = localStorage.getItem(key);
  sessionStorage.setItem(key, previous ?? "");
  localStorage.setItem(key, new Date().toISOString());
  return previous;
}

function toast(message: string): void {
  const el = document.createElement("div");
  el.className = "toast";
  el.setAttribute("role", "status");
  el.textContent = message;
  document.body.append(el);
  setTimeout(() => el.remove(), 4000);
}

// --- login --------------------------------------------------------------------

function renderLogin(): void {
  app.innerHTML = `
    <main class="login">
      <h1>${COPY.loginTitle}</h1>
      <p class="muted">${COPY.loginHint}</p>
      <form data-form="login">
        <input type="email" name="email" required autocomplete="email" placeholder="email" />
        <button type="submit" class="btn-primary">${COPY.sendLink}</button>
      </form>
      <p class="login-msg" role="status"></p>
    </main>`;
}

async function onLogin(form: HTMLFormElement): Promise<void> {
  const email = String(new FormData(form).get("email") ?? "").trim();
  const msg = app.querySelector(".login-msg") as HTMLElement;
  try {
    await backend.sendLink(email);
    msg.textContent = COPY.linkSent(email);
  } catch (err) {
    msg.textContent = err instanceof NotAllowedError ? COPY.notAllowed : COPY.loadError;
  }
}

// --- main page ----------------------------------------------------------------

function renderShell(): void {
  app.innerHTML = `
    ${backend.mode === "preview" ? `<p class="preview-banner">${COPY.preview}</p>` : ""}
    <header class="top">
      <h1>Casa Almería</h1>
      <div class="top-actions">
        <button class="btn-ghost" data-action="toggle-mode"></button>
        ${backend.mode === "live" ? `<button class="btn-ghost" data-action="sign-out">Sair</button>` : ""}
      </div>
    </header>
    <div class="criteria-wrap"></div>
    <nav class="tabs" aria-label="Vistas"></nav>
    <div class="filter-bar"></div>
    <main class="content"><p class="empty">${COPY.loading}</p></main>
    <footer class="health"></footer>
    <dialog class="sheet"></dialog>`;
}

function counts(): Record<View, number> {
  const now = new Date();
  return {
    new: state.cards.filter((c) => isNew(c, state.lastVisit, now) && !isRejected(c)).length,
    all: state.cards.filter((c) => !isRejected(c)).length,
    liked: state.cards.filter(isLiked).length,
  };
}

async function render(): Promise<void> {
  const snap = state.snapshot;
  if (!snap) return;
  const now = new Date();
  (app.querySelector(".criteria-wrap") as HTMLElement).innerHTML = summaryHtml(
    snap.summary,
    state.cards.length,
    now,
    state.criteriaOpen,
  );
  (app.querySelector(".tabs") as HTMLElement).innerHTML = tabsHtml(state.view, counts());
  (app.querySelector(".filter-bar") as HTMLElement).innerHTML = filterChipsHtml(state.filters);
  (app.querySelector("[data-action=toggle-mode]") as HTMLElement).textContent =
    state.mode === "list" ? "Mapa" : "Lista";
  (app.querySelector(".health") as HTMLElement).innerHTML = healthHtml(sourceHealth(snap.runs, now));

  const shown = selectCards(state.cards, state.view, state.filters, state.lastVisit, now);
  const content = app.querySelector(".content") as HTMLElement;
  if (state.mode === "map") {
    const { renderMap } = await import("./map");
    renderMap(content, shown);
    return;
  }
  content.innerHTML = shown.length
    ? `<div class="grid">${shown
        .map((c) => cardHtml(c, state.me, snap.people, state.lastVisit, now))
        .join("")}</div>`
    : emptyHtml(state.view);
}

function rebuildCards(): void {
  const snap = state.snapshot as Snapshot;
  state.cards = buildCards(snap.listings, snap.reactions);
}

async function loadAndRender(): Promise<void> {
  renderShell();
  try {
    state.snapshot = await backend.load();
  } catch {
    (app.querySelector(".content") as HTMLElement).innerHTML =
      `<p class="empty">${COPY.loadError}</p>`;
    return;
  }
  rebuildCards();
  await render();
}

function cardFor(el: Element): Card | undefined {
  const group = el.closest<HTMLElement>("[data-group]")?.dataset.group;
  return state.cards.find((c) => c.groupId === group);
}

async function saveMine(card: Card, reaction: ReactionKind | null, note: string | null) {
  const snap = state.snapshot as Snapshot;
  const before = snap.reactions;
  snap.reactions = [
    ...before.filter((r) => !(r.group_id === card.groupId && r.user_email === state.me)),
    {
      group_id: card.groupId,
      user_email: state.me,
      reaction,
      note,
      updated_at: new Date().toISOString(),
    },
  ];
  rebuildCards();
  await render();
  try {
    await backend.saveReaction(card.groupId, reaction, note);
  } catch {
    snap.reactions = before;
    rebuildCards();
    await render();
    toast(COPY.saveError);
  }
}

function partnerName(): string {
  const people = state.snapshot?.people ?? {};
  const other = Object.keys(people).find((e) => e !== state.me);
  return other ? displayName(other, people) : "A outra pessoa";
}

// --- events -------------------------------------------------------------------

app.addEventListener("click", async (event) => {
  const target = event.target as HTMLElement;
  const chip = target.closest<HTMLElement>("[data-chip]");
  if (chip?.dataset.chip) {
    state.filters = toggleChip(state.filters, chip.dataset.chip);
    localStorage.setItem("filters", JSON.stringify(state.filters));
    await render();
    return;
  }
  const viewBtn = target.closest<HTMLElement>("[data-view]");
  if (viewBtn) {
    state.view = viewBtn.dataset.view as View;
    await render();
    return;
  }
  const action = target.closest<HTMLElement>("[data-action]")?.dataset.action;
  const sheet = app.querySelector("dialog.sheet") as HTMLDialogElement | null;
  switch (action) {
    case "toggle-mode":
      state.mode = state.mode === "list" ? "map" : "list";
      if (state.mode === "list") renderShell();
      await render();
      break;
    case "sign-out":
      await backend.signOut();
      renderLogin();
      break;
    case "open-filters": {
      if (!sheet) break;
      const listings = state.snapshot?.listings ?? [];
      const areas = [...new Set(listings.map((l) => l.area_key).filter(Boolean))] as string[];
      const sources = [...new Set(listings.map((l) => l.source))];
      sheet.innerHTML = filterSheetHtml(state.filters, areas.sort(), sources.sort());
      sheet.showModal();
      break;
    }
    case "clear-filters":
      state.filters = { ...EMPTY_FILTERS };
      localStorage.setItem("filters", JSON.stringify(state.filters));
      sheet?.close();
      await render();
      break;
    case "like":
    case "reject": {
      const card = cardFor(target);
      if (!card) break;
      const mine = myReaction(card, state.me);
      const next = mine?.reaction === action ? null : action;
      await saveMine(card, next, mine?.note ?? null);
      break;
    }
  }
});

// Remember whether the "A procurar" details are open, so re-renders don't close them.
// `toggle` doesn't bubble, hence the capture listener.
app.addEventListener(
  "toggle",
  (event) => {
    const target = event.target as HTMLElement;
    if (target instanceof HTMLDetailsElement && target.classList.contains("criteria")) {
      state.criteriaOpen = target.open;
    }
  },
  true,
);

app.addEventListener("submit", async (event) => {
  const form = event.target as HTMLFormElement;
  event.preventDefault();
  if (form.dataset.form === "login") await onLogin(form);
  if (form.dataset.form === "filters") {
    state.filters = readFilters(form);
    localStorage.setItem("filters", JSON.stringify(state.filters));
    (app.querySelector("dialog.sheet") as HTMLDialogElement).close();
    await render();
  }
});

app.addEventListener("change", async (event) => {
  const target = event.target as HTMLElement;
  if (!(target instanceof HTMLTextAreaElement) || target.dataset.action !== "note") return;
  const card = cardFor(target);
  if (!card) return;
  const mine = myReaction(card, state.me);
  const note = target.value.trim() || null;
  if (!note && mine?.note && !window.confirm(COPY.deleteNote(card.main.title, partnerName()))) {
    target.value = mine.note;
    return;
  }
  await saveMine(card, mine?.reaction ?? null, note);
});

// --- start --------------------------------------------------------------------

async function start(): Promise<void> {
  const email = await backend.currentEmail();
  if (!email) {
    renderLogin();
    return;
  }
  state.me = email;
  state.lastVisit = resolveLastVisit(email);
  await loadAndRender();
}

void start();
