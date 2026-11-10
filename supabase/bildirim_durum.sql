-- TMPRO · Yönetim → Aboneler'de üyenin bildirim durumu (kaç cihazda açık). Tekrar çalıştırılabilir.
create or replace function public.admin_push_counts() returns table (user_id uuid, n int)
language plpgsql stable security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'yetkisiz'; end if;
  return query select s.user_id, count(*)::int from push_subs s group by s.user_id;
end $$;
grant execute on function public.admin_push_counts() to authenticated;
notify pgrst, 'reload schema';
