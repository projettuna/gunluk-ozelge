-- TMPRO: Takip bildirimine dokununca doğrudan kayıt açılsın (tek kayıt: okuyucu, çok kayıt: liste)
create or replace function public.run_watch() returns int
language plpgsql security definer set search_path = public as $$
declare u record; cutoff bigint; total int := 0; n int; first_title text; first_word text; ids text;
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
    select count(*), (array_agg(i.title order by i.id desc))[1], (array_agg(ins.word order by ins.item_id desc))[1],
           string_agg(ins.item_id::text, ',' order by ins.item_id desc)
      into n, first_title, first_word, ids
    from ins join items i on i.id = ins.item_id;
    update profiles set watch_last_id = cutoff where id = u.id;
    if n > 0 then
      total := total + n;
      if not is_muted(u.mute, 'takip') then perform notify_user_url(u.id,
        case when n = 1 then '🔎 Takip: ' || first_word else '🔎 Takip listenizde ' || n || ' yeni kayıt' end,
        first_title, case when n = 1 then '/?kayit=' || ids else '/?kayitlar=' || array_to_string((string_to_array(ids, ','))[1:30], ',') end); end if;
    end if;
  end loop;
  return total;
end $$;
revoke execute on function public.run_watch() from public, anon, authenticated;
grant execute on function public.run_watch() to service_role;
notify pgrst, 'reload schema';
