-- TMPRO · Sohbet iyileştirmeleri. Tekrar çalıştırılabilir.
-- 1) Arkadaşlar birbirinin gerçek adını görür; diğer herkes için adlar yıldızlı kalır.
-- 2) Kişi o sohbet ekranındayken aynı sohbetten anlık bildirim gitmez.
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
notify pgrst, 'reload schema';
