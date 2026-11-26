create table if not exists search_summary (
  id text primary key,
  criteria jsonb not null,
  counts jsonb not null,
  updated_at timestamptz not null
);

grant all on search_summary to service_role;
grant select on search_summary to authenticated;
revoke all on search_summary from anon;

alter table search_summary enable row level security;

drop policy if exists "allowed read summary" on search_summary;
create policy "allowed read summary" on search_summary
  for select to authenticated using (is_allowed());
