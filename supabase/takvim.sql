-- TMPRO: günaydın bildirimi (08:30), hava durumu konumu ve kişisel takvim
create extension if not exists pg_net with schema extensions;
create extension if not exists pg_cron;

alter table public.profiles add column if not exists morning_on boolean not null default true;
alter table public.profiles add column if not exists wx_lat double precision;
alter table public.profiles add column if not exists wx_lon double precision;
alter table public.profiles add column if not exists wx_city text;

create or replace function public.set_morning(enabled boolean) returns void
language sql security definer set search_path = public as $$
  update profiles set morning_on = enabled where id = auth.uid();
$$;
create or replace function public.set_my_location(lat double precision, lon double precision, city text) returns void
language sql security definer set search_path = public as $$
  update profiles set wx_lat = round(lat::numeric, 2), wx_lon = round(lon::numeric, 2), wx_city = left(city, 60) where id = auth.uid();
$$;
grant execute on function public.set_morning(boolean), public.set_my_location(double precision, double precision, text) to authenticated;

-- Kişisel takvim: her üye yalnızca kendi kayıtlarını görür
create table if not exists public.user_events (
  id bigserial primary key,
  user_id uuid not null default auth.uid() references public.profiles(id) on delete cascade,
  title text not null check (length(title) between 1 and 80),
  day date not null,
  yearly boolean not null default true,
  created_at timestamptz not null default now()
);
alter table public.user_events enable row level security;
drop policy if exists "etkinlik: kendisi okur" on public.user_events;
create policy "etkinlik: kendisi okur" on public.user_events for select using (user_id = auth.uid());
drop policy if exists "etkinlik: kendisi ekler" on public.user_events;
create policy "etkinlik: kendisi ekler" on public.user_events for insert with check (user_id = auth.uid() and is_active());
drop policy if exists "etkinlik: kendisi siler" on public.user_events;
create policy "etkinlik: kendisi siler" on public.user_events for delete using (user_id = auth.uid());
grant select, insert, delete on public.user_events to authenticated;
grant usage on sequence public.user_events_id_seq to authenticated;

-- Sabah bildirimi: kullanıcıları, konumlarını ve bugünkü kişisel etkinliklerini aktarıcıya yollar;
-- hava durumu ve resmî tatil mesajı aktarıcıda (Cloudflare) hazırlanır.
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

-- Her sabah 08:30 (Türkiye) = 05:30 UTC
select cron.unschedule(jobid) from cron.job where jobname = 'tmpro-gunaydin';
select cron.schedule('tmpro-gunaydin', '30 5 * * *', 'select public.send_morning(false)');
