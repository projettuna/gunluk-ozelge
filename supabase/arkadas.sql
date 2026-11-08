-- TMPRO · Arkadaş kodu ve onaylı özel mesaj
-- Özel mesaj yalnızca karşılıklı onaylanmış arkadaşlar arasında yazılabilir (yönetici hariç: destek için).
-- Diğer üyelerin adı her yerde baş harfleri görünecek şekilde yıldızlanır (M**** Y*****).
-- Tekrar çalıştırılabilir.

-- 1) Ad maskeleme
create or replace function public.mask_name(n text) returns text
language sql immutable as $$
  select coalesce(string_agg(left(w, 1) || repeat('*', greatest(char_length(w) - 1, 2)), ' '), '***')
  from regexp_split_to_table(trim(coalesce(n, '')), '\s+') w where w <> '';
$$;

create or replace function public.public_name(uid uuid) returns text
language sql stable security definer set search_path = public as $$
  select mask_name(coalesce(nullif(trim(full_name), ''), username)) from profiles where id = uid;
$$;

-- 2) Arkadaş kodu (6 karakter, karışmayan harf/rakamlar)
alter table public.profiles add column if not exists friend_code text;
create or replace function public.gen_friend_code() returns text
language plpgsql volatile set search_path = public as $$
declare c text; abc text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
begin
  loop
    c := '';
    for i in 1..6 loop c := c || substr(abc, 1 + floor(random() * length(abc))::int, 1); end loop;
    exit when not exists (select 1 from profiles where friend_code = c);
  end loop;
  return c;
end $$;
update public.profiles set friend_code = gen_friend_code() where friend_code is null;
create unique index if not exists profiles_friend_code on public.profiles (friend_code);

create or replace function public.trg_friend_code() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.friend_code is null then new.friend_code := gen_friend_code(); end if;
  return new;
end $$;
drop trigger if exists profiles_friend_code on public.profiles;
create trigger profiles_friend_code before insert on public.profiles for each row execute function public.trg_friend_code();

-- 3) Arkadaşlıklar (a < b, tek satır)
create table if not exists public.friendships (
  a uuid not null references auth.users(id) on delete cascade,
  b uuid not null references auth.users(id) on delete cascade,
  requester uuid not null,
  status text not null default 'pending' check (status in ('pending', 'accepted')),
  created_at timestamptz not null default now(),
  primary key (a, b),
  check (a < b)
);
alter table public.friendships enable row level security;
-- Doğrudan erişim yok; yalnızca aşağıdaki fonksiyonlarla

create or replace function public.are_friends(x uuid, y uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from friendships where a = least(x, y) and b = greatest(x, y) and status = 'accepted');
$$;

-- Özel mesaj yazma izni: arkadaşlar arasında ya da taraflardan biri yönetici ise
create or replace function public.can_write_room(r text) returns boolean
language plpgsql stable security definer set search_path = public as $$
declare other uuid;
begin
  if not can_see_room(r) then return false; end if;
  if r not like 'dm:%' then return true; end if;
  begin
    select x::uuid into other from unnest(string_to_array(substring(r from 4), ':')) x where x <> auth.uid()::text limit 1;
  exception when others then return false; end;
  if other is null then return false; end if;
  return is_admin() or exists (select 1 from profiles where id = other and role = 'admin') or are_friends(auth.uid(), other);
end $$;

drop policy if exists "sohbet: aktif üyeler yazar" on public.messages;
create policy "sohbet: aktif üyeler yazar" on public.messages for insert with check (is_active() and can_write_room(room));

-- 4) İstek gönder / yanıtla / çıkar
create or replace function public.friend_request(code text) returns text
language plpgsql security definer set search_path = public as $$
declare other uuid; x uuid; y uuid; f friendships;
begin
  if not is_active() then raise exception 'yetkisiz'; end if;
  select id into other from profiles where friend_code = upper(trim(code))
    and (role = 'admin' or (status = 'active' and (expires_at is null or expires_at > now())));
  if other is null then return 'bulunamadi'; end if;
  if other = auth.uid() then return 'kendin'; end if;
  x := least(auth.uid(), other); y := greatest(auth.uid(), other);
  select * into f from friendships where a = x and b = y;
  if found then
    if f.status = 'accepted' then return 'zaten'; end if;
    if f.requester = auth.uid() then return 'bekliyor'; end if;
    update friendships set status = 'accepted' where a = x and b = y;   -- karşı taraf zaten istemişti
    perform notify_user(other, 'Arkadaşlık kabul edildi', public_name(auth.uid()) || ' ile artık mesajlaşabilirsiniz.');
    return 'kabul';
  end if;
  if (select count(*) from friendships where requester = auth.uid() and status = 'pending' and created_at > now() - interval '1 day') >= 20 then
    return 'sinir';
  end if;
  insert into friendships (a, b, requester) values (x, y, auth.uid());
  perform notify_user(other, 'Yeni arkadaşlık isteği', public_name(auth.uid()) || ' sizi arkadaş olarak eklemek istiyor. Sohbet → Arkadaşlar');
  return 'gonderildi';
end $$;

create or replace function public.friend_respond(other uuid, accept boolean) returns void
language plpgsql security definer set search_path = public as $$
begin
  if accept then
    update friendships set status = 'accepted'
    where a = least(auth.uid(), other) and b = greatest(auth.uid(), other) and status = 'pending' and requester = other;
    if found then perform notify_user(other, 'Arkadaşlık kabul edildi', public_name(auth.uid()) || ' ile artık mesajlaşabilirsiniz.'); end if;
  else
    delete from friendships where a = least(auth.uid(), other) and b = greatest(auth.uid(), other);
  end if;
end $$;

create or replace function public.friend_remove(other uuid) returns void
language sql security definer set search_path = public as $$
  delete from friendships where a = least(auth.uid(), other) and b = greatest(auth.uid(), other);
$$;

create or replace function public.my_friend_code() returns text
language sql stable security definer set search_path = public as $$
  select friend_code from profiles where id = auth.uid();
$$;

-- Arkadaşlar ve istekler: kind = 'friend' | 'in' (bana gelen) | 'out' (benim gönderdiğim)
drop function if exists public.list_friends();
create or replace function public.list_friends() returns table (id uuid, name text, unvan text, avatar text, kind text, is_admin boolean)
language sql stable security definer set search_path = public as $$
  select p.id, public_name(p.id), p.unvan,
         case when f.status = 'accepted' then p.avatar end,
         case when f.status = 'accepted' then 'friend' when f.requester = auth.uid() then 'out' else 'in' end,
         p.role = 'admin'
  from friendships f
  join profiles p on p.id = case when f.a = auth.uid() then f.b else f.a end
  where is_active() and (f.a = auth.uid() or f.b = auth.uid())
  order by f.created_at desc;
$$;

-- Eski üye listesi artık yalnızca arkadaşları döndürür (adlar yıldızlı)
drop function if exists public.list_members();
create or replace function public.list_members() returns table (id uuid, username text, full_name text, unvan text, avatar text)
language sql stable security definer set search_path = public as $$
  select l.id, l.name, l.name, l.unvan, l.avatar from list_friends() l where l.kind = 'friend';
$$;
grant execute on function public.friend_request(text), public.friend_respond(uuid, boolean), public.friend_remove(uuid),
  public.my_friend_code(), public.list_friends(), public.list_members() to authenticated;

-- 5) Sohbette adlar yıldızlı görünsün
create or replace function public.messages_fill() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  new.user_id := auth.uid();
  select mask_name(coalesce(nullif(trim(full_name), ''), username)), unvan into new.username, new.unvan from profiles where id = auth.uid();
  new.created_at := now();
  return new;
end $$;
update public.messages m set username = public_name(m.user_id) where username is distinct from public_name(m.user_id);

-- Bildirimde gönderen adı da yıldızlı
create or replace function public.notify_chat() returns trigger
language plpgsql security definer set search_path = public, extensions as $$
declare subs jsonb; vpriv text; vpub text; relay text; sender text; title text; body text;
begin
  begin
    select value into vpriv from private_settings where key = 'vapid_private';
    select value into vpub from private_settings where key = 'vapid_public';
    select value into relay from private_settings where key = 'push_relay';
    if vpriv is null or vpub is null or relay is null then return new; end if;

    select jsonb_agg(jsonb_build_object('endpoint', s.endpoint, 'p256dh', s.p256dh, 'auth', s.auth)) into subs
    from push_subs s join profiles p on p.id = s.user_id
    where p.id <> new.user_id and p.chat_notify and not (new.room = any (p.muted_rooms))
      and (p.role = 'admin' or (p.status = 'active' and (p.expires_at is null or p.expires_at > now())))
      and (new.room in ('genel','mevzuat','ymm')
           or (new.room like 'dm:%' and position(p.id::text in new.room) > 0)
           or (new.room like 'g:%' and exists (select 1 from chat_group_members m
                                                where m.group_id::text = substring(new.room from 3) and m.user_id = p.id)));
    if subs is null then return new; end if;

    sender := public_name(new.user_id);
    if new.room like 'dm:%' then title := sender; body := new.body;
    else
      title := case new.room when 'genel' then 'Genel Sohbet' when 'mevzuat' then 'Mevzuat Bilgi' when 'ymm' then 'YMM Çalışma Grubu'
               else coalesce((select name from chat_groups where id::text = substring(new.room from 3)), 'Grup') end;
      body := sender || ': ' || new.body;
    end if;

    perform net.http_post(
      url := relay,
      body := jsonb_build_object('vapid', jsonb_build_object('private', vpriv, 'public', vpub),
                                 'subs', subs,
                                 'payload', jsonb_build_object('title', title, 'body', left(body, 180),
                                   'url', '/?room=' || new.room, 'tag', 'chat-' || new.room)),
      headers := '{"Content-Type": "application/json"}'::jsonb);
  exception when others then
    raise warning 'notify_chat: %', sqlerrm;
  end;
  return new;
end $$;

-- Grup listesinde kurucu adı da yıldızlı
create or replace function public.list_groups() returns table
  (id uuid, name text, locked boolean, members bigint, is_member boolean, is_owner boolean, owner_name text, created_at timestamptz)
language sql stable security definer set search_path = public as $$
  select g.id, g.name, g.pass_hash is not null,
         (select count(*) from chat_group_members m where m.group_id = g.id),
         exists (select 1 from chat_group_members m where m.group_id = g.id and m.user_id = auth.uid()),
         g.owner = auth.uid(),
         public_name(g.owner),
         g.created_at
  from chat_groups g where is_active() order by g.created_at desc;
$$;
