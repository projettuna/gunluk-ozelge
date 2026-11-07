-- TMPRO: üyelerin kurduğu gruplar (isteğe bağlı şifreli)
create extension if not exists pgcrypto with schema extensions;

create table if not exists public.chat_groups (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 2 and 60),
  owner uuid not null references auth.users(id) on delete cascade,
  pass_hash text,
  created_at timestamptz not null default now()
);
create table if not exists public.chat_group_members (
  group_id uuid not null references public.chat_groups(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  joined_at timestamptz not null default now(),
  primary key (group_id, user_id)
);
alter table public.chat_groups enable row level security;
alter table public.chat_group_members enable row level security;
-- Doğrudan erişim yok; her şey aşağıdaki fonksiyonlarla

create or replace function public.is_group_member(gid uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from chat_group_members where group_id = gid and user_id = auth.uid());
$$;

-- Odaya erişim: açık odalar, taraf olunan özel mesajlar, üye olunan gruplar
create or replace function public.can_see_room(r text) returns boolean
language plpgsql stable security definer set search_path = public as $$
begin
  if r in ('genel','mevzuat','ymm') then return true; end if;
  if r like 'dm:%' then return position(auth.uid()::text in r) > 0; end if;
  if r like 'g:%' then
    begin return is_group_member(substring(r from 3)::uuid);
    exception when others then return false; end;
  end if;
  return false;
end $$;

create or replace function public.list_groups() returns table
  (id uuid, name text, locked boolean, members bigint, is_member boolean, is_owner boolean, owner_name text, created_at timestamptz)
language sql stable security definer set search_path = public as $$
  select g.id, g.name, g.pass_hash is not null,
         (select count(*) from chat_group_members m where m.group_id = g.id),
         exists (select 1 from chat_group_members m where m.group_id = g.id and m.user_id = auth.uid()),
         g.owner = auth.uid(),
         (select coalesce(p.full_name, p.username) from profiles p where p.id = g.owner),
         g.created_at
  from chat_groups g where is_active() order by g.created_at desc;
$$;

create or replace function public.create_group(gname text, gpass text default null) returns uuid
language plpgsql security definer set search_path = public, extensions as $$
declare gid uuid;
begin
  if not is_active() then raise exception 'yetkisiz'; end if;
  insert into chat_groups (name, owner, pass_hash)
  values (trim(gname), auth.uid(), case when coalesce(gpass, '') = '' then null else crypt(gpass, gen_salt('bf')) end)
  returning id into gid;
  insert into chat_group_members (group_id, user_id) values (gid, auth.uid());
  return gid;
end $$;

create or replace function public.join_group(gid uuid, gpass text default null) returns boolean
language plpgsql security definer set search_path = public, extensions as $$
declare h text;
begin
  if not is_active() then raise exception 'yetkisiz'; end if;
  select pass_hash into h from chat_groups where id = gid;
  if not found then return false; end if;
  if h is not null and (gpass is null or crypt(gpass, h) <> h) then return false; end if;
  insert into chat_group_members (group_id, user_id) values (gid, auth.uid()) on conflict do nothing;
  return true;
end $$;

create or replace function public.leave_group(gid uuid) returns void
language sql security definer set search_path = public as $$
  delete from chat_group_members where group_id = gid and user_id = auth.uid();
$$;

create or replace function public.delete_group(gid uuid) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not exists (select 1 from chat_groups where id = gid and (owner = auth.uid() or is_admin())) then raise exception 'yetkisiz'; end if;
  delete from messages where room = 'g:' || gid::text;
  delete from chat_groups where id = gid;
end $$;

grant execute on function public.list_groups(), public.create_group(text, text), public.join_group(uuid, text),
  public.leave_group(uuid), public.delete_group(uuid) to authenticated;

-- Grup sahibi kendi grubundaki mesajları silebilir
drop policy if exists "sohbet: kendi mesajını veya yönetici siler" on public.messages;
create policy "sohbet: kendi mesajını veya yönetici siler" on public.messages for delete
  using (user_id = auth.uid() or (is_admin() and room not like 'dm:%'));
