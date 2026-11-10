-- TMPRO: Yönetici için üye kullanım/kopma riski görünümü (yalnız sayılar; içerik okunmaz)
create or replace function public.admin_kullanim() returns jsonb
language plpgsql stable security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'yetkisiz'; end if;
  return (select coalesce(jsonb_agg(jsonb_build_object(
      'name', coalesce(nullif(trim(p.full_name), ''), p.username),
      'last', greatest(p.app_seen_at, (select max(day)::timestamptz from usage_daily u where u.user_id = p.id)),
      'gun30', (select count(distinct day) from usage_daily u where u.user_id = p.id and u.day >= current_date - 29),
      'not', (select count(*) from item_notes n where n.user_id = p.id),
      'takip', coalesce(array_length(p.watch_words, 1), 0),
      'madde', coalesce(array_length(p.madde_takip, 1), 0),
      'cihaz', (select count(*) from push_subs s where s.user_id = p.id),
      'asistan', (select coalesce(sum(n), 0) from ai_usage a where a.user_id = p.id),
      'emsal', (select coalesce(sum(n), 0) from usage_daily u where u.user_id = p.id and u.kind = 'emsal'),
      'kinds', (select coalesce(jsonb_agg(distinct kind), '[]') from usage_daily u where u.user_id = p.id)
    ) order by p.app_seen_at nulls first), '[]')
    from profiles p
    where p.role <> 'admin' and p.status = 'active' and p.username <> 'nobetci'
      and (p.expires_at is null or p.expires_at > now()));
end $$;
grant execute on function public.admin_kullanim() to authenticated;
notify pgrst, 'reload schema';
