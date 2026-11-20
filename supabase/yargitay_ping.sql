-- Yargıtay telefonu her çalıştığında "buradayım" der; nöbetçi telefonun durumunu buradan anlar.
create or replace function public.yargitay_ping(token text, info jsonb default '{}'::jsonb)
returns void language plpgsql security definer set search_path to 'public' as $$
begin
  if token is null or token <> (select value from private_settings where key = 'ingest_token') then raise exception 'yetkisiz'; end if;
  insert into private_settings (key, value)
  values ('yargitay_ping', jsonb_build_object('t', now(), 'info', coalesce(info, '{}'::jsonb))::text)
  on conflict (key) do update set value = excluded.value;
end $$;
revoke all on function public.yargitay_ping(text, jsonb) from public;
grant execute on function public.yargitay_ping(text, jsonb) to anon, authenticated;
