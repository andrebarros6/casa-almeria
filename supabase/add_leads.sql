-- Lead tracker: run once in the Supabase SQL Editor (New query, paste, Run).

-- One row per card (dedupe group) you are pursuing.
create table if not exists leads (
  group_id text primary key,
  stage text not null check (stage in (
    'contactado', 'respondeu', 'visita', 'visitado', 'candidatura', 'fechado',
    'sem_resposta', 'ja_alugado', 'descartado'
  )),
  stage_at timestamptz not null default now(),   -- when it entered this stage
  next_action_at timestamptz,                     -- e.g. the visit date/time
  reason text,                                    -- why discarded
  updated_by text not null default (auth.jwt() ->> 'email'),
  updated_at timestamptz not null default now()
);

-- What happened, by whom, when (both partners see everything).
create table if not exists lead_events (
  id bigint generated always as identity primary key,
  group_id text not null,
  user_email text not null default (auth.jwt() ->> 'email'),
  kind text not null,            -- stage | contact | note
  body text,
  at timestamptz not null default now()
);
create index if not exists lead_events_group on lead_events (group_id, at);

-- Household documents checklist (not per flat).
create table if not exists documents (
  key text primary key,
  ready boolean not null default false,
  note text,
  owner text,
  updated_by text not null default (auth.jwt() ->> 'email'),
  updated_at timestamptz not null default now()
);
alter table documents add column if not exists owner text;  -- for tables made before owner existed

grant all on leads, lead_events, documents to service_role;
grant usage, select on all sequences in schema public to service_role, authenticated;
grant select, insert, update, delete on leads, lead_events, documents to authenticated;
revoke all on leads, lead_events, documents from anon;

alter table leads enable row level security;
alter table lead_events enable row level security;
alter table documents enable row level security;

drop policy if exists "allowed all leads" on leads;
create policy "allowed all leads" on leads for all to authenticated
  using (is_allowed()) with check (is_allowed());

drop policy if exists "allowed all lead events" on lead_events;
create policy "allowed all lead events" on lead_events for all to authenticated
  using (is_allowed()) with check (is_allowed() and user_email = auth.jwt() ->> 'email');

drop policy if exists "allowed all documents" on documents;
create policy "allowed all documents" on documents for all to authenticated
  using (is_allowed()) with check (is_allowed());
