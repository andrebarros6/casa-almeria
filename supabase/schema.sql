-- Almería Rental Finder schema. Run once in the Supabase SQL editor.
-- The scraper writes with the service-role key (bypasses RLS).
-- The web page reads with the anon key + a logged-in user, limited to allowed_users.

create table if not exists allowed_users (
  email text primary key,
  display_name text          -- shown on the page: "{display_name} gostou"
);

create table if not exists listings (
  id text primary key,                 -- "<source>:<source_id>"
  source text not null,
  source_id text not null,
  url text not null,
  title text not null,
  description text not null default '',
  price_eur integer not null,
  bedrooms integer,
  bathrooms integer,
  area_m2 integer,
  floor integer,
  property_type text check (property_type in ('flat', 'house')),
  municipality text,
  neighbourhood text,
  area_key text,
  lat double precision,
  lng double precision,
  photos jsonb not null default '[]',
  features text[] not null default '{}',
  published_at date,
  is_temporary boolean not null default false,
  features_known boolean not null default true,
  first_seen timestamptz,
  last_seen timestamptz,
  gone boolean not null default false,
  group_id text,
  rejected_reason text,
  price_history jsonb not null default '[]',
  commute_min integer
);
create index if not exists listings_visible on listings (gone, rejected_reason);
create index if not exists listings_source_seen on listings (source, last_seen);
create index if not exists listings_group on listings (group_id);

create table if not exists source_runs (
  id bigint generated always as identity primary key,
  source text not null,
  started_at timestamptz not null,
  finished_at timestamptz,
  status text not null check (status in ('ok', 'blocked', 'error')),
  found integer not null default 0,
  new integer not null default 0,
  new_matches integer not null default 0,
  updated integer not null default 0,
  gone integer not null default 0,
  error text
);
create index if not exists source_runs_recent on source_runs (source, started_at desc);

-- Shared ❤️/❌/notes, keyed by dedupe group so a flat on 3 portals has one reaction.
create table if not exists reactions (
  group_id text not null,
  user_email text not null default (auth.jwt() ->> 'email'),
  reaction text check (reaction in ('like', 'reject')),
  note text,
  updated_at timestamptz not null default now(),
  primary key (group_id, user_email)
);

-- What the page shows at the top: search criteria + discard counts from the latest run.
create table if not exists search_summary (
  id text primary key,          -- always 'latest'
  criteria jsonb not null,
  counts jsonb not null,
  updated_at timestamptz not null
);

-- API access. Newer Supabase projects don't grant table access to API roles automatically.
-- anon (not logged in) gets nothing. authenticated users are further limited by RLS below.
grant usage on schema public to service_role, authenticated;
grant all on listings, source_runs, reactions, allowed_users, search_summary to service_role;
grant usage, select on all sequences in schema public to service_role;
grant select on listings, source_runs, allowed_users, search_summary to authenticated;
grant select, insert, update, delete on reactions to authenticated;
revoke all on listings, source_runs, reactions, allowed_users, search_summary from anon;

-- Row-level security
alter table allowed_users enable row level security;
alter table listings enable row level security;
alter table source_runs enable row level security;
alter table reactions enable row level security;
alter table search_summary enable row level security;

create or replace function is_allowed() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from allowed_users where email = auth.jwt() ->> 'email');
$$;

drop policy if exists "allowed read people" on allowed_users;
create policy "allowed read people" on allowed_users for select to authenticated using (is_allowed());

drop policy if exists "allowed read listings" on listings;
create policy "allowed read listings" on listings for select to authenticated using (is_allowed());

drop policy if exists "allowed read runs" on source_runs;
create policy "allowed read runs" on source_runs for select to authenticated using (is_allowed());

drop policy if exists "allowed read summary" on search_summary;
create policy "allowed read summary" on search_summary for select to authenticated using (is_allowed());

drop policy if exists "allowed read reactions" on reactions;
create policy "allowed read reactions" on reactions for select to authenticated using (is_allowed());

drop policy if exists "own write reactions" on reactions;
create policy "own write reactions" on reactions for all to authenticated
  using (is_allowed() and user_email = auth.jwt() ->> 'email')
  with check (is_allowed() and user_email = auth.jwt() ->> 'email');

-- Add the two of you (edit before running):
-- insert into allowed_users (email, display_name) values ('you@example.com', '<your name>'), ('partner@example.com', '<partner name>');
