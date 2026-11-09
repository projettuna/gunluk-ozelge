-- TMPRO · Haftalık özet bildirimi (Cuma 17:00) açık/kapalı tercihi. Tekrar çalıştırılabilir.
alter table public.profiles add column if not exists weekly_on boolean not null default true;
create or replace function public.set_weekly(enabled boolean) returns void
language sql security definer set search_path = public as $$
  update profiles set weekly_on = enabled where id = auth.uid();
$$;
grant execute on function public.set_weekly(boolean) to authenticated;
notify pgrst, 'reload schema';
