// Data access: Supabase when configured (VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY),
// otherwise a local preview that reads /sample.json and keeps edits in localStorage.

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { DocItem, Lead, LeadEvent, StoredStage } from "./leads";
import type { Listing, Reaction, ReactionKind, SearchSummary, SourceRun } from "./logic";

export interface Snapshot {
  listings: Listing[];
  reactions: Reaction[];
  runs: SourceRun[];
  people: Record<string, string>;
  summary: SearchSummary | null;
  leads: Lead[];
  events: LeadEvent[];
  documents: DocItem[];
}

export interface LeadUpdate {
  stage: StoredStage;
  next_action_at?: string | null;
  reason?: string | null;
}

export interface Backend {
  mode: "live" | "preview";
  currentEmail(): Promise<string | null>;
  sendLink(email: string): Promise<void>;
  signOut(): Promise<void>;
  load(): Promise<Snapshot>;
  saveReaction(groupId: string, reaction: ReactionKind | null, note: string | null): Promise<void>;
  /** Set a lead's stage (null = back to just "interessa"). Returns the stored lead. */
  saveLead(groupId: string, update: LeadUpdate | null): Promise<Lead | null>;
  addEvent(groupId: string, kind: LeadEvent["kind"], body: string | null): Promise<LeadEvent>;
  saveDocument(doc: DocItem): Promise<void>;
}

export class NotAllowedError extends Error {}

const URL = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const KEY = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export function createBackend(): Backend {
  return URL && KEY ? new SupabaseBackend(createClient(URL, KEY)) : new PreviewBackend();
}

function newLead(groupId: string, update: LeadUpdate, by: string, previous?: Lead): Lead {
  const now = new Date().toISOString();
  const sameStage = previous?.stage === update.stage;
  return {
    group_id: groupId,
    stage: update.stage,
    stage_at: sameStage && previous ? previous.stage_at : now,
    next_action_at:
      update.next_action_at !== undefined ? update.next_action_at : (previous?.next_action_at ?? null),
    reason: update.reason !== undefined ? update.reason : (previous?.reason ?? null),
    updated_by: by,
    updated_at: now,
  };
}

class SupabaseBackend implements Backend {
  mode = "live" as const;
  private leads = new Map<string, Lead>();
  constructor(private db: SupabaseClient) {}

  async currentEmail(): Promise<string | null> {
    const { data } = await this.db.auth.getSession();
    return data.session?.user.email ?? null;
  }

  async sendLink(email: string): Promise<void> {
    const { error } = await this.db.auth.signInWithOtp({
      email,
      // Only the two whitelisted emails have accounts; no sign-ups.
      options: { emailRedirectTo: window.location.href.split("#")[0], shouldCreateUser: false },
    });
    if (error) {
      if (/signups not allowed|not found|invalid/i.test(error.message)) throw new NotAllowedError();
      throw error;
    }
  }

  async signOut(): Promise<void> {
    await this.db.auth.signOut();
  }

  async load(): Promise<Snapshot> {
    const since = new Date(Date.now() - 14 * 86_400_000).toISOString();
    const [listings, reactions, runs, people, summary, leads, events, documents] = await Promise.all([
      this.db.from("listings").select("*").eq("gone", false).is("rejected_reason", null),
      this.db.from("reactions").select("*"),
      this.db
        .from("source_runs")
        .select("source,started_at,status,found,new_matches")
        .gte("started_at", since),
      this.db.from("allowed_users").select("email,display_name"),
      this.db.from("search_summary").select("criteria,counts,updated_at").eq("id", "latest").maybeSingle(),
      this.db.from("leads").select("*"),
      this.db.from("lead_events").select("group_id,user_email,kind,body,at").order("at"),
      this.db.from("documents").select("key,ready,note"),
    ]);
    for (const res of [listings, reactions, runs, people, summary, leads, events, documents]) {
      if (res.error) throw res.error;
    }
    this.leads = new Map(((leads.data ?? []) as Lead[]).map((l) => [l.group_id, l]));
    return {
      listings: (listings.data ?? []) as Listing[],
      reactions: (reactions.data ?? []) as Reaction[],
      runs: (runs.data ?? []) as SourceRun[],
      people: Object.fromEntries(
        ((people.data ?? []) as { email: string; display_name: string | null }[])
          .filter((p) => p.display_name)
          .map((p) => [p.email, p.display_name as string]),
      ),
      summary: (summary.data ?? null) as SearchSummary | null,
      leads: [...this.leads.values()],
      events: (events.data ?? []) as LeadEvent[],
      documents: (documents.data ?? []) as DocItem[],
    };
  }

  async saveReaction(groupId: string, reaction: ReactionKind | null, note: string | null) {
    const email = await this.currentEmail();
    const { error } = await this.db.from("reactions").upsert({
      group_id: groupId,
      user_email: email,
      reaction,
      note,
      updated_at: new Date().toISOString(),
    });
    if (error) throw error;
  }

  async saveLead(groupId: string, update: LeadUpdate | null): Promise<Lead | null> {
    if (!update) {
      const { error } = await this.db.from("leads").delete().eq("group_id", groupId);
      if (error) throw error;
      this.leads.delete(groupId);
      return null;
    }
    const lead = newLead(groupId, update, (await this.currentEmail()) ?? "", this.leads.get(groupId));
    const { error } = await this.db.from("leads").upsert(lead);
    if (error) throw error;
    this.leads.set(groupId, lead);
    return lead;
  }

  async addEvent(groupId: string, kind: LeadEvent["kind"], body: string | null): Promise<LeadEvent> {
    const event: LeadEvent = {
      group_id: groupId,
      user_email: (await this.currentEmail()) ?? "",
      kind,
      body,
      at: new Date().toISOString(),
    };
    const { error } = await this.db.from("lead_events").insert(event);
    if (error) throw error;
    return event;
  }

  async saveDocument(doc: DocItem): Promise<void> {
    const { error } = await this.db
      .from("documents")
      .upsert({ ...doc, updated_by: await this.currentEmail(), updated_at: new Date().toISOString() });
    if (error) throw error;
  }
}

const PREVIEW_EMAIL = "preview@local";
const KEYS = {
  reactions: "casa-almeria-preview-reactions",
  leads: "casa-almeria-preview-leads",
  events: "casa-almeria-preview-events",
  documents: "casa-almeria-preview-documents",
};

function readLocal<T>(key: string): T[] {
  return JSON.parse(localStorage.getItem(key) ?? "[]") as T[];
}

class PreviewBackend implements Backend {
  mode = "preview" as const;

  async currentEmail() {
    return PREVIEW_EMAIL;
  }
  async sendLink() {}
  async signOut() {}

  async load(): Promise<Snapshot> {
    const res = await fetch(`${import.meta.env.BASE_URL}sample.json`);
    if (!res.ok) throw new Error(`sample.json: ${res.status}`);
    const data = (await res.json()) as {
      listings: Listing[];
      runs: SourceRun[];
      summary?: SearchSummary | null;
    };
    return {
      listings: data.listings,
      runs: data.runs,
      reactions: readLocal<Reaction>(KEYS.reactions),
      people: { [PREVIEW_EMAIL]: "Tu" },
      summary: data.summary ?? null,
      leads: readLocal<Lead>(KEYS.leads),
      events: readLocal<LeadEvent>(KEYS.events),
      documents: readLocal<DocItem>(KEYS.documents),
    };
  }

  async saveReaction(groupId: string, reaction: ReactionKind | null, note: string | null) {
    const rest = readLocal<Reaction>(KEYS.reactions).filter(
      (r) => !(r.group_id === groupId && r.user_email === PREVIEW_EMAIL),
    );
    rest.push({
      group_id: groupId,
      user_email: PREVIEW_EMAIL,
      reaction,
      note,
      updated_at: new Date().toISOString(),
    });
    localStorage.setItem(KEYS.reactions, JSON.stringify(rest));
  }

  async saveLead(groupId: string, update: LeadUpdate | null): Promise<Lead | null> {
    const all = readLocal<Lead>(KEYS.leads);
    const previous = all.find((l) => l.group_id === groupId);
    const rest = all.filter((l) => l.group_id !== groupId);
    const lead = update ? newLead(groupId, update, PREVIEW_EMAIL, previous) : null;
    localStorage.setItem(KEYS.leads, JSON.stringify(lead ? [...rest, lead] : rest));
    return lead;
  }

  async addEvent(groupId: string, kind: LeadEvent["kind"], body: string | null): Promise<LeadEvent> {
    const event: LeadEvent = {
      group_id: groupId,
      user_email: PREVIEW_EMAIL,
      kind,
      body,
      at: new Date().toISOString(),
    };
    localStorage.setItem(KEYS.events, JSON.stringify([...readLocal<LeadEvent>(KEYS.events), event]));
    return event;
  }

  async saveDocument(doc: DocItem): Promise<void> {
    const rest = readLocal<DocItem>(KEYS.documents).filter((d) => d.key !== doc.key);
    localStorage.setItem(KEYS.documents, JSON.stringify([...rest, doc]));
  }
}
