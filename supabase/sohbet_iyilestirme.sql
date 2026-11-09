-- TMPRO · Sohbet iyileştirmeleri. Tekrar çalıştırılabilir.
-- 1) Arkadaşlar birbirinin gerçek adını görür; diğer herkes için adlar yıldızlı kalır.
-- 2) Kişi o sohbet ekranındayken aynı sohbetten anlık bildirim gitmez.
-- 3) Süreli susturma: tüm bildirimler ya da tek bir tür 1/3/6/12/24 saat susturulabilir.
alter table public.profiles add column if not exists mute jsonb not null default '{}'::jsonb;
create or replace function public.is_muted(m jsonb, k text) returns boolean
language sql stable as $$
  select coalesce((m->>'hepsi')::timestamptz > now(), false) or coalesce((m->>k)::timestamptz > now(), false);
$$;
-- k: hepsi / mevzuat / sohbet / gunaydin / takip ya da bir kayıt türü; saat null ya da 0 ise susturma kalkar
create or replace function public.set_mute(k text, saat int) returns jsonb
language plpgsql security definer set search_path = public as $$
declare m jsonb;
begin
  select coalesce(mute, '{}'::jsonb) into m from profiles where id = auth.uid();
  -- süresi geçenleri temizle
  select coalesce(jsonb_object_agg(key, value), '{}'::jsonb) into m from jsonb_each_text(m) where value::timestamptz > now();
  if coalesce(saat, 0) <= 0 then m := m - k;
  else m := m || jsonb_build_object(left(k, 40), now() + make_interval(hours => least(saat, 168)));
  end if;
  update profiles set mute = m where id = auth.uid();
  return m;
end $$;
grant execute on function public.set_mute(text, int) to authenticated;
alter table public.profiles add column if not exists active_room text;
alter table public.profiles add column if not exists active_at timestamptz;
create or replace function public.set_active_room(r text) returns void
language sql security definer set search_path = public as $$
  update profiles set active_room = left(r, 80), active_at = now() where id = auth.uid();
$$;
grant execute on function public.set_active_room(text) to authenticated;

create or replace function public.list_friends() returns table (id uuid, name text, unvan text, avatar text, kind text, is_admin boolean)
language sql stable security definer set search_path = public as $$
  select p.id,
         case when f.status = 'accepted' then coalesce(nullif(trim(p.full_name), ''), p.username) else public_name(p.id) end,
         p.unvan,
         case when f.status = 'accepted' then p.avatar end,
         case when f.status = 'accepted' then 'friend' when f.requester = auth.uid() then 'out' else 'in' end,
         p.role = 'admin'
  from friendships f
  join profiles p on p.id = case when f.a = auth.uid() then f.b else f.a end
  where is_active() and (f.a = auth.uid() or f.b = auth.uid())
  order by f.created_at desc;
$$;

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
      and not coalesce(p.active_room = new.room and p.active_at > now() - interval '45 seconds', false)  -- o sohbette ekrandaysa bildirim yok
      and not is_muted(p.mute, 'sohbet')
      and (p.role = 'admin' or (p.status = 'active' and (p.expires_at is null or p.expires_at > now())))
      and (new.room in ('genel','mevzuat','ymm')
           or (new.room like 'dm:%' and position(p.id::text in new.room) > 0)
           or (new.room like 'g:%' and exists (select 1 from chat_group_members m
                                                where m.group_id::text = substring(new.room from 3) and m.user_id = p.id)));
    if subs is null then return new; end if;

    sender := public_name(new.user_id);
    if new.room like 'dm:%' then
      -- özel mesajda alıcı arkadaşsa gönderenin gerçek adı görünür
      title := sender;
      if are_friends(split_part(new.room, ':', 2)::uuid, split_part(new.room, ':', 3)::uuid) then
        select coalesce(nullif(trim(full_name), ''), username) into title from profiles where id = new.user_id;
      end if;
      body := new.body;
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

-- Günaydın ve Takip Listesi bildirimleri de susturmaya uyar
create or replace function public.send_morning(test boolean default false) returns integer
language plpgsql security definer set search_path = public, extensions as $$
declare vpriv text; vpub text; relay text; users jsonb; today date := (now() at time zone 'Europe/Istanbul')::date;
begin
  select value into vpriv from private_settings where key = 'vapid_private';
  select value into vpub from private_settings where key = 'vapid_public';
  select value into relay from private_settings where key = 'push_relay';
  if vpriv is null or vpub is null or relay is null then return 0; end if;

  select jsonb_agg(jsonb_build_object(
           'name', coalesce(p.full_name, p.username), 'lat', p.wx_lat, 'lon', p.wx_lon, 'city', p.wx_city,
           'events', coalesce((select jsonb_agg(e.title order by e.id) from user_events e
                               where e.user_id = p.id and (e.day = today or (e.yearly and to_char(e.day, 'MM-DD') = to_char(today, 'MM-DD')))), '[]'::jsonb),
           'news', (select jsonb_object_agg(x.tur, x.n) from (select it.tur, count(*) n from items it
                    where it.created_at > now() - interval '24 hours' and it.eklendi is not null
                      and it.tur = any (coalesce(p.notify_types, '{}')) group by it.tur order by count(*) desc) x),
           'subs', (select jsonb_agg(jsonb_build_object('endpoint', s.endpoint, 'p256dh', s.p256dh, 'auth', s.auth))
                    from push_subs s where s.user_id = p.id)))
    into users
  from profiles p
  where exists (select 1 from push_subs s where s.user_id = p.id)
    and (case when test then p.role = 'admin'
              else p.morning_on and not is_muted(p.mute, 'gunaydin') and (p.role = 'admin' or (p.status = 'active' and (p.expires_at is null or p.expires_at > now()))) end);
  if users is null then return 0; end if;

  perform net.http_post(
    url := replace(relay, '/api/push', '/api/morning'),
    body := jsonb_build_object('vapid', jsonb_build_object('private', vpriv, 'public', vpub), 'users', users),
    headers := '{"Content-Type": "application/json"}'::jsonb,
    timeout_milliseconds := 60000);
  return jsonb_array_length(users);
end $$;

create or replace function public.run_watch() returns int
language plpgsql security definer set search_path = public as $$
declare u record; cutoff bigint; total int := 0; n int; first_title text; first_word text;
begin
  select coalesce((select min(id) - 1 from items where metin is null and created_at > now() - interval '6 hours'),
                  (select max(id) from items)) into cutoff;
  for u in select p.id, p.watch_words, p.watch_last_id, p.mute from profiles p
           where cardinality(p.watch_words) > 0
             and (p.role = 'admin' or (p.status = 'active' and (p.expires_at is null or p.expires_at > now()))) loop
    if u.watch_last_id is null then
      update profiles set watch_last_id = cutoff where id = u.id; continue;
    end if;
    if cutoff <= u.watch_last_id then continue; end if;
    with ins as (
      insert into watch_hits (user_id, item_id, word)
      select u.id, it.id, w from items it cross join unnest(u.watch_words) w
      where it.id > u.watch_last_id and it.id <= cutoff and it.eklendi is not null
        and tr_norm(it.title || ' ' || coalesce(it.ozet, '') || ' ' || coalesce(it.metin, '')) like '%' || tr_norm(w) || '%'
      on conflict (user_id, item_id) do nothing
      returning item_id, word)
    select count(*), (array_agg(i.title order by i.id desc))[1], (array_agg(ins.word order by ins.item_id desc))[1]
      into n, first_title, first_word
    from ins join items i on i.id = ins.item_id;
    update profiles set watch_last_id = cutoff where id = u.id;
    if n > 0 then
      total := total + n;
      if not is_muted(u.mute, 'takip') then perform notify_user_url(u.id,
        case when n = 1 then '🔎 Takip: ' || first_word else '🔎 Takip listenizde ' || n || ' yeni kayıt' end,
        first_title, '/?takip=1'); end if;
    end if;
  end loop;
  return total;
end $$;

notify pgrst, 'reload schema';
