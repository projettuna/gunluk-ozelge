-- TMPRO: bildirim teslim kaydı. Telefon bildirimi aldığında service worker push_ack çağırır;
-- gönderim (sunucu) ve teslim (cihaz) saatleri karşılaştırılarak gecikme ölçülür. Yalnız saat ve tür tutulur.
create table if not exists public.push_acks (
  id bigserial primary key,
  user_id uuid references auth.users(id) on delete cascade,
  tag text,
  sent_at timestamptz,
  received_at timestamptz not null default now(),
  host text
);
create index if not exists push_acks_recv_idx on public.push_acks (received_at desc);
create index if not exists push_acks_user_idx on public.push_acks (user_id);
alter table public.push_acks enable row level security;  -- doğrudan erişim yok; yalnız aşağıdaki işlevler

create or replace function public.push_ack(p_endpoint text, p_tag text, p_sent bigint)
returns void language plpgsql security definer set search_path = public as $$
declare uid uuid;
begin
  select user_id into uid from push_subs where endpoint = p_endpoint limit 1;
  if uid is null then return; end if;  -- bilinmeyen abonelik: sessizce yok say
  insert into push_acks (user_id, tag, sent_at, host)
  values (uid, left(p_tag, 40),
          case when p_sent between 1700000000000 and 4100000000000 then to_timestamp(p_sent / 1000.0) end,
          split_part(p_endpoint, '/', 3));
  delete from push_acks where received_at < now() - interval '30 days';
end $$;
revoke all on function public.push_ack(text, text, bigint) from public;
grant execute on function public.push_ack(text, text, bigint) to anon, authenticated;

-- Nöbetçi için: bugünkü Günaydın zamanlayıcı sonucu, aktarıcı yanıtı ve cihazlara teslim gecikmeleri
create or replace function public.morning_status()
returns jsonb language sql security definer set search_path = public, cron, net as $$
  select jsonb_build_object(
    'cron', (select jsonb_build_object('status', d.status, 'start', d.start_time, 'msg', d.return_message)
             from cron.job_run_details d join cron.job j using (jobid)
             where j.jobname = 'tmpro-gunaydin' order by d.start_time desc limit 1),
    'relay', (select jsonb_build_object('code', r.status_code, 'at', r.created, 'err', r.error_msg, 'timed_out', r.timed_out,
                                        'body', case when r.content like '{"today"%' then r.content::jsonb end)
              from net._http_response r,
                   (select d.start_time st from cron.job_run_details d join cron.job j using (jobid)
                    where j.jobname = 'tmpro-gunaydin' order by d.start_time desc limit 1) c
              where r.created between c.st and c.st + interval '3 minutes'
              order by (r.content like '{"today"%') desc, r.created limit 1),
    'acks', (select coalesce(jsonb_agg(jsonb_build_object('u', md5(a.user_id::text), 'gecikme_sn', round(extract(epoch from a.received_at - a.sent_at)))
                                       order by a.received_at), '[]'::jsonb)
             from push_acks a where a.tag = 'tmpro-gunaydin'
               and a.received_at > (date_trunc('day', now() at time zone 'Europe/Istanbul') at time zone 'Europe/Istanbul')),
    'subs', (select count(*) from push_subs s join profiles p on p.id = s.user_id
             where p.morning_on and (p.role = 'admin' or (p.status = 'active' and (p.expires_at is null or p.expires_at > now()))))
  );
$$;
revoke all on function public.morning_status() from public, anon, authenticated;
grant execute on function public.morning_status() to service_role;
