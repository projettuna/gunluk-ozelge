-- TMPRO · Takip Listesi (anahtar kelime alarmı). Tekrar çalıştırılabilir.
-- Üye kelimelerini yazar; bu kelimelerin geçtiği yeni kayıtlar "watch_hits"e düşer ve üyeye bildirim gider.

alter table public.profiles add column if not exists watch_words text[] not null default '{}';
alter table public.profiles add column if not exists watch_last_id bigint;

create table if not exists public.watch_hits (
  user_id uuid not null references auth.users(id) on delete cascade,
  item_id bigint not null references public.items(id) on delete cascade,
  word text not null,
  created_at timestamptz not null default now(),
  primary key (user_id, item_id)
);
alter table public.watch_hits enable row level security;
drop policy if exists "takip: kendi eşleşmeleri" on public.watch_hits;
create policy "takip: kendi eşleşmeleri" on public.watch_hits for select using (user_id = auth.uid());
grant select on public.watch_hits to authenticated;

-- Türkçe büyük/küçük harf duyarsız karşılaştırma için
create or replace function public.tr_norm(t text) returns text
language sql immutable as $$
  select lower(translate(coalesce(t, ''), 'İIĞÜŞÖÇÂÎÛ', 'iığüşöçaiu'));
$$;

-- Kelimeleri kaydet; son 90 günün kayıtlarında hemen arar (bildirim göndermeden)
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
  delete from watch_hits h where h.user_id = auth.uid() and not (h.word = any (clean));
  insert into watch_hits (user_id, item_id, word, created_at)
  select auth.uid(), it.id, w, coalesce(it.eklendi, it.created_at) from items it cross join unnest(clean) w
  where coalesce(it.eklendi, it.created_at) > now() - interval '90 days'
    and tr_norm(it.title || ' ' || coalesce(it.ozet, '') || ' ' || coalesce(it.metin, '')) like '%' || tr_norm(w) || '%'
  on conflict (user_id, item_id) do nothing;
  select count(*) into n from watch_hits where user_id = auth.uid();
  return n;
end $$;
grant execute on function public.set_watch_words(text[]) to authenticated;

-- Bildirim (adres verilebilen sürüm)
create or replace function public.notify_user_url(uid uuid, title text, body text, link text) returns void
language plpgsql security definer set search_path = public, extensions as $$
declare subs jsonb; vpriv text; vpub text; relay text;
begin
  select value into vpriv from private_settings where key = 'vapid_private';
  select value into vpub from private_settings where key = 'vapid_public';
  select value into relay from private_settings where key = 'push_relay';
  if vpriv is null or vpub is null or relay is null then return; end if;
  select jsonb_agg(jsonb_build_object('endpoint', endpoint, 'p256dh', p256dh, 'auth', auth)) into subs from push_subs where user_id = uid;
  if subs is null then return; end if;
  perform net.http_post(url := relay,
    body := jsonb_build_object('vapid', jsonb_build_object('private', vpriv, 'public', vpub), 'subs', subs,
      'payload', jsonb_build_object('title', title, 'body', left(body, 180), 'url', link, 'tag', 'takip-' || extract(epoch from now())::bigint)),
    headers := '{"Content-Type": "application/json"}'::jsonb);
exception when others then raise warning 'notify_user_url: %', sqlerrm;
end $$;
revoke execute on function public.notify_user_url(uuid, text, text, text) from public, anon, authenticated;

-- Otomatik taramadan sonra çağrılır (servis anahtarıyla). Tam metni henüz gelmemiş yeni kayıtları 6 saate kadar bekler.
create or replace function public.run_watch() returns int
language plpgsql security definer set search_path = public as $$
declare u record; cutoff bigint; total int := 0; n int; first_title text; first_word text;
begin
  select coalesce((select min(id) - 1 from items where metin is null and created_at > now() - interval '6 hours'),
                  (select max(id) from items)) into cutoff;
  for u in select p.id, p.watch_words, p.watch_last_id from profiles p
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
    select count(*), (array_agg(i.title order by i.id desc))[1], (array_agg(ins.word order by ins.item_id desc))[1]
      into n, first_title, first_word
    from ins join items i on i.id = ins.item_id;
    update profiles set watch_last_id = cutoff where id = u.id;
    if n > 0 then
      total := total + n;
      perform notify_user_url(u.id,
        case when n = 1 then '🔎 Takip: ' || first_word else '🔎 Takip listenizde ' || n || ' yeni kayıt' end,
        first_title, '/?takip=1');
    end if;
  end loop;
  return total;
end $$;
revoke execute on function public.run_watch() from public, anon, authenticated;
grant execute on function public.run_watch() to service_role;

notify pgrst, 'reload schema';
