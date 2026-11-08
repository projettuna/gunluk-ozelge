-- TMPRO · Günaydın bildirimine son 24 saatin mevzuat özeti eklenir. Tekrar çalıştırılabilir.
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
              else p.morning_on and (p.role = 'admin' or (p.status = 'active' and (p.expires_at is null or p.expires_at > now()))) end);
  if users is null then return 0; end if;

  perform net.http_post(
    url := replace(relay, '/api/push', '/api/morning'),
    body := jsonb_build_object('vapid', jsonb_build_object('private', vpriv, 'public', vpub), 'users', users),
    headers := '{"Content-Type": "application/json"}'::jsonb,
    timeout_milliseconds := 60000);
  return jsonb_array_length(users);
end $$;
revoke all on function public.send_morning(boolean) from public, anon, authenticated;
grant execute on function public.send_morning(boolean) to service_role;

notify pgrst, 'reload schema';
