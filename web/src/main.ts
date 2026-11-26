import "./styles.css";
import { type Backend, createBackend, type LeadUpdate, NotAllowedError, RateLimitedError, type Snapshot } from "./data";
import {
  contactMessage,
  DOCUMENTS,
  documentsDone,
  type DocItem,
  type Lead,
  mailtoUrl,
  findEmail,
  processRows,
  type Stage,
  STAGE_LABELS,
  stageCounts,
  stageOf,
  isActive,
} from "./leads";
import {
  contactSheetHtml,
  documentsHtml,
  LEAD_COPY,
  leadSheetHtml,
  processTableHtml,
  stageFilterHtml,
} from "./leadsView";
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
  workPoint,
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

type Page = "homes" | "process" | "docs";

const state = {
  me: "",
  snapshot: null as Snapshot | null,
  cards: [] as Card[],
  leads: new Map<string, Lead>(),
  page: pageFromHash(),
  view: "new" as View,
  mode: "list" as "list" | "map",
  filters: loadFilters(),
  lastVisit: null as string | null,
  criteriaOpen: false,
  processStage: null as Stage | null,
  showFinished: false,
  contactChannel: "portal",
};

function pageFromHash(): Page {
  if (location.hash === "#processo") return "process";
  if (location.hash === "#documentos") return "docs";
  return "homes";
}

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
    msg.textContent =
      err instanceof NotAllowedError
        ? COPY.notAllowed
        : err instanceof RateLimitedError
          ? err.seconds !== null
            ? COPY.linkTooSoon(err.seconds)
            : COPY.linkHourlyLimit
          : COPY.linkSendError;
  }
}

// --- shell --------------------------------------------------------------------

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
    <nav class="pages" aria-label="Páginas"></nav>
    <section class="page-homes">
      <div class="criteria-wrap"></div>
      <nav class="tabs" aria-label="Vistas"></nav>
      <div class="filter-bar"></div>
      <main class="content"><p class="empty">${COPY.loading}</p></main>
      <footer class="health"></footer>
    </section>
    <section class="page-process" hidden></section>
    <section class="page-docs" hidden></section>
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

function inProcessCount(): number {
  return state.cards.filter((c) => {
    const stage = stageOf(c, state.leads);
    return stage !== null && isActive(stage);
  }).length;
}

function renderPagesNav(): void {
  (app.querySelector(".pages") as HTMLElement).innerHTML = `
    <a href="#" class="page-link" aria-current="${state.page === "homes" ? "page" : "false"}">Casas</a>
    <a href="#processo" class="page-link" aria-current="${
      state.page === "process" ? "page" : "false"
    }">Em processo <span class="tab-count">${inProcessCount()}</span></a>
    <a href="#documentos" class="page-link" aria-current="${
      state.page === "docs" ? "page" : "false"
    }">Documentos <span class="tab-count">${documentsDone(state.snapshot?.documents ?? [])}/${
      DOCUMENTS.length
    }</span></a>`;
}

async function render(): Promise<void> {
  const snap = state.snapshot;
  if (!snap) return;
  renderPagesNav();
  const homes = app.querySelector(".page-homes") as HTMLElement;
  const process = app.querySelector(".page-process") as HTMLElement;
  homes.hidden = state.page !== "homes";
  process.hidden = state.page !== "process";
  const docs = app.querySelector(".page-docs") as HTMLElement;
  docs.hidden = state.page !== "docs";
  const toggle = app.querySelector("[data-action=toggle-mode]") as HTMLElement;
  toggle.hidden = state.page !== "homes";
  if (state.page === "process") {
    renderProcess(process, snap);
    return;
  }
  if (state.page === "docs") {
    docs.innerHTML = documentsHtml(snap.documents, snap.people);
    return;
  }
  const now = new Date();
  (app.querySelector(".criteria-wrap") as HTMLElement).innerHTML = summaryHtml(
    snap.summary,
    state.cards.length,
    now,
    state.criteriaOpen,
  );
  (app.querySelector(".tabs") as HTMLElement).innerHTML = tabsHtml(state.view, counts());
  (app.querySelector(".filter-bar") as HTMLElement).innerHTML = filterChipsHtml(
    state.filters,
    workPoint(snap.summary) !== null,
  );
  toggle.textContent = state.mode === "list" ? "Mapa" : "Lista";
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
        .map((c) =>
          cardHtml(c, state.me, snap.people, state.lastVisit, now, stageOf(c, state.leads)),
        )
        .join("")}</div>`
    : emptyHtml(state.view);
}

function renderProcess(el: HTMLElement, snap: Snapshot): void {
  const now = new Date();
  const rows = processRows(
    state.cards,
    state.leads,
    snap.events,
    { showFinished: state.showFinished, stage: state.processStage },
    now,
  );
  el.innerHTML = `
    ${stageFilterHtml(stageCounts(state.cards, state.leads), state.processStage, state.showFinished)}
    ${
      !rows.length && state.processStage
        ? `<p class="empty">${LEAD_COPY.emptyStage}</p>`
        : processTableHtml(rows, snap.people, now)
    }`;
}

function rebuildCards(): void {
  const snap = state.snapshot as Snapshot;
  state.cards = buildCards(snap.listings, snap.reactions, workPoint(snap.summary));
  state.leads = new Map(snap.leads.map((l) => [l.group_id, l]));
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

function sheet(): HTMLDialogElement {
  return app.querySelector("dialog.sheet") as HTMLDialogElement;
}

// --- reactions ----------------------------------------------------------------

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

/** Both of you, sender first: "André y Bea". */
function senderNames(): string[] {
  const people = state.snapshot?.people ?? {};
  const others = Object.keys(people).filter((e) => e !== state.me);
  return [state.me, ...others].map((e) => displayName(e, people));
}

// --- leads --------------------------------------------------------------------

/** Absolute date for the history ("27/11 18:00"); relative words would go stale. */
function visitLabel(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function setStage(card: Card, update: LeadUpdate | null, note?: string): Promise<void> {
  const snap = state.snapshot as Snapshot;
  try {
    const lead = await backend.saveLead(card.groupId, update);
    snap.leads = snap.leads.filter((l) => l.group_id !== card.groupId);
    if (lead) snap.leads.push(lead);
    const label = update ? STAGE_LABELS[update.stage] : STAGE_LABELS.interessa;
    snap.events.push(await backend.addEvent(card.groupId, "stage", note ? `${label}: ${note}` : label));
    if (!update && !isLiked(card)) await saveMine(card, "like", myReaction(card, state.me)?.note ?? null);
  } catch {
    toast(COPY.saveError);
  }
  rebuildCards();
  await render();
}

function openContact(card: Card): void {
  sheet().innerHTML = contactSheetHtml(card, contactMessage(card, senderNames()), findEmail(card));
  sheet().showModal();
}

function openLead(card: Card): void {
  const snap = state.snapshot as Snapshot;
  sheet().innerHTML = leadSheetHtml(
    card,
    stageOf(card, state.leads),
    state.leads.get(card.groupId) ?? null,
    snap.events.filter((e) => e.group_id === card.groupId),
    snap.people,
    new Date(),
  );
  if (!sheet().open) sheet().showModal();
}

// --- events -------------------------------------------------------------------

window.addEventListener("hashchange", async () => {
  state.page = pageFromHash();
  await render();
});

app.addEventListener("click", async (event) => {
  const target = event.target as HTMLElement;
  const chip = target.closest<HTMLElement>("[data-chip]");
  if (chip?.dataset.chip) {
    state.filters = toggleChip(state.filters, chip.dataset.chip);
    localStorage.setItem("filters", JSON.stringify(state.filters));
    await render();
    return;
  }
  const stageFilter = target.closest<HTMLElement>("[data-stage-filter]");
  if (stageFilter) {
    state.processStage = (stageFilter.dataset.stageFilter || null) as Stage | null;
    await render();
    return;
  }
  const setStageBtn = target.closest<HTMLElement>("[data-set-stage]");
  if (setStageBtn) {
    const card = cardFor(setStageBtn);
    const stage = setStageBtn.dataset.setStage as Stage;
    if (card) {
      await setStage(card, stage === "interessa" ? null : { stage });
      openLead(card);
    }
    return;
  }
  const viewBtn = target.closest<HTMLElement>("[data-view]");
  if (viewBtn) {
    state.view = viewBtn.dataset.view as View;
    await render();
    return;
  }
  const actionEl = target.closest<HTMLElement>("[data-action]");
  const action = actionEl?.dataset.action;
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
      const listings = state.snapshot?.listings ?? [];
      const areas = [...new Set(listings.map((l) => l.area_key).filter(Boolean))] as string[];
      const sources = [...new Set(listings.map((l) => l.source))];
      sheet().innerHTML = filterSheetHtml(state.filters, areas.sort(), sources.sort());
      sheet().showModal();
      break;
    }
    case "clear-filters":
      state.filters = { ...EMPTY_FILTERS };
      localStorage.setItem("filters", JSON.stringify(state.filters));
      if (sheet().open) sheet().close();
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
    case "contact": {
      const card = cardFor(target);
      if (card) openContact(card);
      break;
    }
    case "open-lead": {
      const card = cardFor(target);
      if (card) openLead(card);
      break;
    }
    case "copy-open": {
      const message = (sheet().querySelector("textarea") as HTMLTextAreaElement).value;
      state.contactChannel = "portal";
      try {
        await navigator.clipboard.writeText(message);
        toast(LEAD_COPY.copied);
      } catch {
        toast(LEAD_COPY.copyFailed);
      }
      window.open(actionEl?.dataset.url, "_blank", "noopener,noreferrer");
      break;
    }
    case "send-email": {
      const card = cardFor(target);
      const message = (sheet().querySelector("textarea") as HTMLTextAreaElement).value;
      if (card && actionEl?.dataset.email) {
        state.contactChannel = "email";
        window.location.href = mailtoUrl(actionEl.dataset.email, card, message);
      }
      break;
    }
    case "mark-sent": {
      const card = cardFor(target);
      if (!card) break;
      sheet().close();
      const snap = state.snapshot as Snapshot;
      try {
        snap.events.push(await backend.addEvent(card.groupId, "contact", state.contactChannel));
      } catch {
        toast(COPY.saveError);
      }
      if (!isLiked(card)) await saveMine(card, "like", myReaction(card, state.me)?.note ?? null);
      await setStage(card, { stage: "contactado" });
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
    sheet().close();
    await render();
  }
  if (form.dataset.form === "lead") {
    const card = cardFor(form);
    const input = form.querySelector<HTMLInputElement>("input[name=note]");
    const note = input?.value.trim();
    if (!card || !note) return;
    try {
      (state.snapshot as Snapshot).events.push(await backend.addEvent(card.groupId, "note", note));
    } catch {
      toast(COPY.saveError);
    }
    openLead(card);
    await render();
  }
});

app.addEventListener("change", async (event) => {
  const target = event.target as HTMLElement;
  const snap = state.snapshot as Snapshot;
  const docKey = target.dataset.doc ?? target.dataset.docOwner ?? target.dataset.docNote;
  if (docKey && (target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) {
    const before = snap.documents.find((d) => d.key === docKey);
    const doc: DocItem = { key: docKey, ready: false, note: null, owner: null, ...before };
    if (target.dataset.doc) doc.ready = (target as HTMLInputElement).checked;
    if (target.dataset.docOwner) doc.owner = target.value || null;
    if (target.dataset.docNote) doc.note = target.value.trim() || null;
    snap.documents = [...snap.documents.filter((d) => d.key !== docKey), doc];
    try {
      await backend.saveDocument(doc);
    } catch {
      toast(COPY.saveError);
    }
    await render();
    return;
  }
  if (target instanceof HTMLInputElement && target.dataset.action === "show-finished") {
    state.showFinished = target.checked;
    await render();
    return;
  }
  if (target.dataset.action === "visit-at" || target.dataset.action === "reason") {
    const card = cardFor(target);
    const value = (target as HTMLInputElement | HTMLSelectElement).value;
    if (!card) return;
    if (target.dataset.action === "visit-at") {
      const at = value ? new Date(value).toISOString() : null;
      const current = state.leads.get(card.groupId);
      if (current?.stage === "visita" && current.next_action_at === at) return; // nothing changed
      await setStage(card, { stage: "visita", next_action_at: at }, at ? visitLabel(at) : undefined);
    } else {
      await setStage(card, { stage: "descartado", reason: value || null }, value || undefined);
    }
    openLead(card);
    return;
  }
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
