-- TMPRO sohbet: odalar (genel, mevzuat, ymm) ve üyeler arası özel mesajlar
alter table public.profiles add column if not exists unvan text check (char_length(unvan) <= 60);
create table if not exists public.messages (
  id bigserial primary key,
  room text not null default 'genel',
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  username text,
  body text not null check (char_length(body) between 1 and 2000),
  created_at timestamptz not null default now()
);
alter table public.messages add column if not exists room text not null default 'genel';
alter table public.messages add column if not exists unvan text;
create index if not exists messages_room_id on public.messages (room, id desc);

-- Kullanıcı adı profilden alınır (taklit edilemez)
create or replace function public.messages_fill() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  new.user_id := auth.uid();
  select username, unvan into new.username, new.unvan from profiles where id = auth.uid();
  new.created_at := now();
  return new;
end $$;
drop trigger if exists messages_fill on public.messages;
create trigger messages_fill before insert on public.messages for each row execute function public.messages_fill();

-- Odaya erişim: herkese açık odalar veya kişinin taraf olduğu özel sohbet (dm:<id1>:<id2>)
create or replace function public.can_see_room(r text) returns boolean
language sql stable as $$
  select r in ('genel','mevzuat','ymm') or (r like 'dm:%' and position(auth.uid()::text in r) > 0);
$$;

alter table public.messages enable row level security;
drop policy if exists "sohbet: aktif üyeler okur" on public.messages;
create policy "sohbet: aktif üyeler okur" on public.messages for select using (is_active() and can_see_room(room));
drop policy if exists "sohbet: aktif üyeler yazar" on public.messages;
create policy "sohbet: aktif üyeler yazar" on public.messages for insert with check (is_active() and can_see_room(room));
drop policy if exists "sohbet: kendi mesajını veya yönetici siler" on public.messages;
create policy "sohbet: kendi mesajını veya yönetici siler" on public.messages for delete using (user_id = auth.uid() or (is_admin() and room not like 'dm:%'));

-- Özel mesaj için üye listesi (yalnızca aktif üyeler görür)
drop function if exists public.list_members();
create or replace function public.list_members() returns table (id uuid, username text, full_name text, unvan text)
language sql stable security definer set search_path = public as $$
  select p.id, p.username, p.full_name, p.unvan from profiles p
  where is_active() and p.id <> auth.uid()
    and (p.role = 'admin' or (p.status = 'active' and (p.expires_at is null or p.expires_at > now())))
  order by coalesce(p.full_name, p.username);
$$;
grant execute on function public.list_members() to authenticated;

-- Anlık güncelleme
do $$ begin
  alter publication supabase_realtime add table public.messages;
exception when duplicate_object then null; end $$;

-- Ünvan: kayıtta girilir, Hesap ekranından değiştirilir
create or replace function public.set_my_unvan(u text) returns void
language sql security definer set search_path = public as $$
  update profiles set unvan = nullif(left(trim(u), 60), '') where id = auth.uid();
$$;
grant execute on function public.set_my_unvan(text) to authenticated;

create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into profiles (id, username, full_name, phone, unvan, pay_code, role, status)
  values (new.id,
          lower(coalesce(new.raw_user_meta_data->>'username', split_part(new.email, '@', 1))),
          new.raw_user_meta_data->>'full_name',
          new.raw_user_meta_data->>'phone',
          nullif(left(trim(new.raw_user_meta_data->>'unvan'), 60), ''),
          'TM' || lpad((floor(random() * 900000) + 100000)::int::text, 6, '0'),
          case when exists (select 1 from profiles) then 'user' else 'admin' end,
          case when exists (select 1 from profiles) then 'pending' else 'active' end);
  return new;
end $$;
