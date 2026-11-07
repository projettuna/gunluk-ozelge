-- TMPRO sohbet: üyeler arası mesajlaşma
create table if not exists public.messages (
  id bigserial primary key,
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  username text,
  body text not null check (char_length(body) between 1 and 2000),
  created_at timestamptz not null default now()
);
create index if not exists messages_id_desc on public.messages (id desc);

-- Kullanıcı adı profilden alınır (taklit edilemez)
create or replace function public.messages_fill() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  new.user_id := auth.uid();
  new.username := (select username from profiles where id = auth.uid());
  new.created_at := now();
  return new;
end $$;
drop trigger if exists messages_fill on public.messages;
create trigger messages_fill before insert on public.messages for each row execute function public.messages_fill();

alter table public.messages enable row level security;
drop policy if exists "sohbet: aktif üyeler okur" on public.messages;
create policy "sohbet: aktif üyeler okur" on public.messages for select using (is_active());
drop policy if exists "sohbet: aktif üyeler yazar" on public.messages;
create policy "sohbet: aktif üyeler yazar" on public.messages for insert with check (is_active());
drop policy if exists "sohbet: kendi mesajını veya yönetici siler" on public.messages;
create policy "sohbet: kendi mesajını veya yönetici siler" on public.messages for delete using (user_id = auth.uid() or is_admin());

-- Anlık güncelleme
do $$ begin
  alter publication supabase_realtime add table public.messages;
exception when duplicate_object then null; end $$;
