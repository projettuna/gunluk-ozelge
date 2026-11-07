-- TMPRO: sohbet bildirimleri ve sessize alma
create extension if not exists pg_net with schema extensions;

alter table public.profiles add column if not exists chat_notify boolean not null default true;
alter table public.profiles add column if not exists muted_rooms text[] not null default '{}';

insert into public.private_settings (key, value) values
  ('vapid_public', 'BPFqONiJVewhJkbAMU5jxn410HsBjrGNPSXFmQcWdHJBmVA73ufFqN4IlAiglZ75XB2kZUHz90sVRBjd_Lpeg50'),
  ('push_relay', 'https://tmpro.tmproapp.workers.dev/api/push')
on conflict (key) do update set value = excluded.value;

create or replace function public.set_chat_notify(enabled boolean) returns void
language sql security definer set search_path = public as $$
  update profiles set chat_notify = enabled where id = auth.uid();
$$;

create or replace function public.set_room_mute(r text, muted boolean) returns void
language sql security definer set search_path = public as $$
  update profiles set muted_rooms = case when muted then array(select distinct unnest(muted_rooms || r))
                                         else array_remove(muted_rooms, r) end
  where id = auth.uid();
$$;
grant execute on function public.set_chat_notify(boolean), public.set_room_mute(text, boolean) to authenticated;

-- Yeni mesajda alıcılara anlık bildirim (Cloudflare aktarıcısı üzerinden)
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

    select coalesce(full_name, username) into sender from profiles where id = new.user_id;
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
drop trigger if exists messages_notify on public.messages;
create trigger messages_notify after insert on public.messages for each row execute function public.notify_chat();
