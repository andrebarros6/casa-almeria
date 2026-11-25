// Data access: Supabase when configured (VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY),
// otherwise a local preview that reads /sample.json and keeps reactions in localStorage.

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { Listing, Reaction, ReactionKind, SourceRun } from "./logic";

export interface Snapshot {
  listings: Listing[];
  reactions: Reaction[];
  runs: SourceRun[];
  people: Record<string, string>;
}

export interface Backend {
  mode: "live" | "preview";
  currentEmail(): Promise<string | null>;
  sendLink(email: string): Promise<void>;
  signOut(): Promise<void>;
  load(): Promise<Snapshot>;
  saveReaction(groupId: string, reaction: ReactionKind | null, note: string | null): Promise<void>;
}

export class NotAllowedError extends Error {}

const URL = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const KEY = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export function createBackend(): Backend {
  return URL && KEY ? new SupabaseBackend(createClient(URL, KEY)) : new PreviewBackend();
}

class SupabaseBackend implements Backend {
  mode = "live" as const;
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
    const [listings, reactions, runs, people] = await Promise.all([
      this.db.from("listings").select("*").eq("gone", false).is("rejected_reason", null),
      this.db.from("reactions").select("*"),
      this.db
        .from("source_runs")
        .select("source,started_at,status,found,new_matches")
        .gte("started_at", since),
      this.db.from("allowed_users").select("email,display_name"),
    ]);
    for (const res of [listings, reactions, runs, people]) if (res.error) throw res.error;
    return {
      listings: (listings.data ?? []) as Listing[],
      reactions: (reactions.data ?? []) as Reaction[],
      runs: (runs.data ?? []) as SourceRun[],
      people: Object.fromEntries(
        ((people.data ?? []) as { email: string; display_name: string | null }[])
          .filter((p) => p.display_name)
          .map((p) => [p.email, p.display_name as string]),
      ),
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
}

const PREVIEW_EMAIL = "preview@local";
const PREVIEW_KEY = "casa-almeria-preview-reactions";

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
    const data = (await res.json()) as { listings: Listing[]; runs: SourceRun[] };
    return {
      listings: data.listings,
      runs: data.runs,
      reactions: JSON.parse(localStorage.getItem(PREVIEW_KEY) ?? "[]") as Reaction[],
      people: { [PREVIEW_EMAIL]: "Tu" },
    };
  }

  async saveReaction(groupId: string, reaction: ReactionKind | null, note: string | null) {
    const all = JSON.parse(localStorage.getItem(PREVIEW_KEY) ?? "[]") as Reaction[];
    const rest = all.filter((r) => !(r.group_id === groupId && r.user_email === PREVIEW_EMAIL));
    rest.push({
      group_id: groupId,
      user_email: PREVIEW_EMAIL,
      reaction,
      note,
      updated_at: new Date().toISOString(),
    });
    localStorage.setItem(PREVIEW_KEY, JSON.stringify(rest));
  }
}
