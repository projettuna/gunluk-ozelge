-- TMPRO · Tam metinde arama: özelge ve kararların tam metninde geçen kelimeleri bulur, eşleşen yerin kısa bir parçasını döndürür.
-- Tekrar çalıştırılabilir.
create or replace function public.search_items(q text) returns table (id bigint, snippet text)
language plpgsql stable security definer set search_path = public as $$
declare ws text[];
begin
  if not is_active() then return; end if;
  ws := array(select w from regexp_split_to_table(tr_norm(trim(coalesce(q, ''))), '\s+') w where length(w) >= 2 limit 6);
  if cardinality(ws) = 0 or length(array_to_string(ws, '')) < 3 then return; end if;
  return query
    select i.id, substr(i.metin, greatest(1, strpos(tr_norm(i.metin), ws[1]) - 90), 240)
    from items i
    where i.metin is not null and i.metin <> ''
      and (select bool_and(strpos(tr_norm(i.metin), w) > 0) from unnest(ws) w)
    order by i.id desc
    limit 150;
end $$;
grant execute on function public.search_items(text) to authenticated;
notify pgrst, 'reload schema';
