-- TMPRO · Kanun maddesi takibi. Tekrar çalıştırılabilir.
-- Üye "KDVK 29" gibi maddeleri takibe alır. Maddeye atıf yapan yeni karar/özelge Takip Listesi'ne düşer;
-- madde metni değişince (günlük kontrol) bildirim gider. Kanun metinleri kamuya açıktır.

alter table public.profiles add column if not exists madde_takip text[] not null default '{}';

create table if not exists public.madde_durum (
  kod text primary key,
  baslik text,
  metin text,
  hash text,
  onceki text,             -- değişiklikten önceki metin
  degisti timestamptz,     -- son değişikliğin fark edildiği an
  kontrol timestamptz      -- son kontrol
);
alter table public.madde_durum enable row level security;
drop policy if exists "madde: üyeler okur" on public.madde_durum;
create policy "madde: üyeler okur" on public.madde_durum for select to authenticated using (true);
grant select on public.madde_durum to authenticated;

create or replace function public.set_madde_takip(maddeler text[]) returns int
language plpgsql security definer set search_path = public as $$
declare clean text[];
begin
  if auth.uid() is null or not is_active() then raise exception 'yetkisiz'; end if;
  select coalesce(array_agg(distinct m), '{}') into clean from unnest(coalesce(maddeler, '{}')) m
  where m ~ '^(VUK|GVK|KVK|KDVK|ÖTVK|DVK|HK|AATUHK|İYUK) ((Ek |Mükerrer )?[0-9]{1,3})$';
  if array_length(clean, 1) > 30 then raise exception 'En fazla 30 madde takip edilebilir'; end if;
  update profiles set madde_takip = clean where id = auth.uid();
  delete from watch_hits h where h.user_id = auth.uid() and h.word ~ '^(VUK|GVK|KVK|KDVK|ÖTVK|DVK|HK|AATUHK|İYUK) ' and not (h.word = any (clean));
  return coalesce(array_length(clean, 1), 0);
end $$;
grant execute on function public.set_madde_takip(text[]) to authenticated;

-- Kelime listesi kaydedilirken madde eşleşmeleri silinmesin
create or replace function public.set_watch_words(words text[]) returns int
language plpgsql security definer set search_path = public as $$
declare clean text[]; n int;
begin
  if auth.uid() is null or not is_active() then raise exception 'yetkisiz'; end if;
  select coalesce(array_agg(distinct w), '{}') into clean from (
    select left(regexp_replace(trim(x), '\s+', ' ', 'g'), 40) w from unnest(coalesce(words, '{}')) x) s
  where char_length(w) >= 3;
  if array_length(clean, 1) > 20 then raise exception 'En fazla 20 kelime eklenebilir'; end if;
  update profiles set watch_words = clean, watch_last_id = coalesce(watch_last_id, (select max(id) from items)) where id = auth.uid();
  delete from watch_hits h where h.user_id = auth.uid() and not (h.word = any (clean))
    and not (h.word = any (coalesce((select madde_takip from profiles where id = auth.uid()), '{}')));
  insert into watch_hits (user_id, item_id, word, created_at)
  select auth.uid(), it.id, w, coalesce(it.eklendi, it.created_at) from items it cross join unnest(clean) w
  where coalesce(it.eklendi, it.created_at) > now() - interval '90 days'
    and tr_norm(it.title || ' ' || coalesce(it.ozet, '') || ' ' || coalesce(it.metin, '')) like '%' || tr_norm(w) || '%'
  on conflict (user_id, item_id) do nothing;
  select count(*) into n from watch_hits where user_id = auth.uid();
  return n;
end $$;
grant execute on function public.set_watch_words(text[]) to authenticated;

grant execute on function public.notify_user_url(uuid, text, text, text) to service_role;

notify pgrst, 'reload schema';
