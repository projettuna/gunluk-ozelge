-- TMPRO · Kayıtlara kişisel not ve klasör. Yalnızca sahibi görür. Tekrar çalıştırılabilir.
create table if not exists public.item_notes (
  user_id uuid not null references auth.users(id) on delete cascade default auth.uid(),
  item_id bigint not null,
  note text not null default '' check (length(note) <= 4000),
  folders text[] not null default '{}',
  updated_at timestamptz not null default now(),
  primary key (user_id, item_id)
);
alter table public.item_notes enable row level security;
drop policy if exists "notlar: yalnızca sahibi" on public.item_notes;
create policy "notlar: yalnızca sahibi" on public.item_notes for all
  using (user_id = auth.uid()) with check (user_id = auth.uid() and cardinality(folders) <= 10);
grant select, insert, update, delete on public.item_notes to authenticated;
notify pgrst, 'reload schema';
