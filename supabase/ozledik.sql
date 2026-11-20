-- TMPRO · "Sizi özledik" hatırlatması
-- 3 günden uzun süredir uygulamayı açmayan üyelere esprili, kısa bir anlık bildirim.
--  * Hafta içi 12:30'da (öğle arası) bakılır; sessiz saatlere (22-08) hiç denk gelmez.
--  * Aynı üyeye en fazla 4 günde bir; üye dönmezse arka arkaya en fazla 3 kez, sonra susar.
--    Üye uygulamayı yeniden açınca sayaç sıfırlanır.
--  * Hesap → Bildirimler → "Ara Sıra Hatırlatma" ile kapatılabilir; Sessize Al (tümü) da geçerlidir.
-- Tekrar çalıştırılabilir.

alter table public.profiles add column if not exists nudge_on boolean not null default true;
alter table public.profiles add column if not exists nudge_at timestamptz;          -- son hatırlatma zamanı
alter table public.profiles add column if not exists nudge_streak int not null default 0; -- dönmeden arka arkaya kaç kez
alter table public.profiles add column if not exists nudge_idx int not null default 0;    -- sıradaki espri

create or replace function public.set_nudge(enabled boolean) returns void
language sql security definer set search_path = public as $$
  update profiles set nudge_on = enabled where id = auth.uid();
$$;
grant execute on function public.set_nudge(boolean) to authenticated;

-- Espri havuzu: {ad} = ilk ad, {gun} = kaç gündür girmedi
create or replace function public.nudge_jokes() returns jsonb
language sql immutable as $$
  select '[
    ["Yoklama yapıyoruz 📋", "{ad}, {gun} gündür ortalarda yoksunuz. Tutanağa \"adreste bulunamadı\" yazmadan bir uğrayın 🙂"],
    ["Özelgeler sizi sordu 📨", "Yeni özelgeler birikti, kendi aralarında \"müfettişimiz nerede?\" diye fısıldaşıyorlar."],
    ["Bu bir ihtarname değildir ✉️", "Sadece dostane bir hatırlatma: TMPRO''da yeni kayıtlar var, kahvenizin yanına iyi gider ☕"],
    ["Defter ve belgeler ibraz edilmedi 😄", "Son {gun} güne ait ziyaret kaydınız bulunamadı. İbraz için uygulamayı bir kez açmanız yeterli."],
    ["Danıştay kararını verdi ⚖️", "Oybirliğiyle: \"{ad} bugün TMPRO''ya bir uğramalıdır.\" Kesin karar, itiraz yolu kapalı 🙂"],
    ["e-Tebligat usulü hatırlatma 📬", "Biliyorsunuz, açmasanız da 5. günün sonunda tebliğ edilmiş sayılırsınız. Yine de biz açmanızı tercih ederiz 😉"],
    ["Pişmanlık zammı yok 😇", "{gun} gün ara verdiniz ama burada gecikme faizi işlemiyor. Kendiliğinden dönen her zaman baş tacı."],
    ["Re''sen hatırlatma 📌", "Sizden ses çıkmayınca TMPRO re''sen harekete geçti. İstenen tek şey: kısa bir uğrama 🙂"],
    ["Takdir komisyonuna sevk etmeden 🧮", "Ziyaret matrahınız {gun} gündür sıfır beyan edildi. Komisyona gitmeden bir kez açmanızı rica ederiz 😄"],
    ["Zamanaşımı henüz işlemedi ⌛", "Ama {gun} gündür yoksunuz. Beş yıl beklemeyelim, bugün bir göz atın 🙂"],
    ["Mevzuat yerinde durmuyor 🏃", "Siz yokken tebliğler yazıldı, sirkülerler çıktı, Resmî Gazete her gece yayımlandı. Hızlı bir göz gezdirme 2 dakika."],
    ["Çay demlendi 🫖", "Özelge, karar, haber… Hepsi masada hazır. Bir bardak çaylık mola verir misiniz, {ad}?"],
    ["Karşıt inceleme talebi 🔍", "Siz yokken gelen kayıtların tutarlılığını bir de sizin gözünüzle incelesek mi?"],
    ["Ek süre talebiniz kabul edildi 📅", "{gun} günlük ek süre doldu sayılır. Rapor beklemiyoruz, sadece bir \"merhaba\" yeter 🙂"],
    ["Mükellef değil, müfettiş arıyoruz 🕵️", "Bu sefer aranan sizsiniz, {ad}! TMPRO''da sizi bekleyen yeni kayıtlar var."]
  ]'::jsonb;
$$;

-- Asıl gönderim. test = true: yalnız yöneticiye, girip girmediğine bakmadan bir örnek gönderir (sayaçları değiştirmez).
create or replace function public.send_nudges(test boolean default false) returns integer
language plpgsql security definer set search_path = public, extensions as $$
declare vpriv text; vpub text; relay text; u record; j jsonb := nudge_jokes(); k int; t text; b text; sent int := 0;
begin
  select value into vpriv from private_settings where key = 'vapid_private';
  select value into vpub from private_settings where key = 'vapid_public';
  select value into relay from private_settings where key = 'push_relay';
  if vpriv is null or vpub is null or relay is null then return 0; end if;

  for u in
    select p.id, p.nudge_idx, p.nudge_at, p.nudge_streak, x.last,
           split_part(nullif(trim(p.full_name), ''), ' ', 1) ad,
           (select jsonb_agg(jsonb_build_object('endpoint', s.endpoint, 'p256dh', s.p256dh, 'auth', s.auth))
              from push_subs s where s.user_id = p.id) subs
    from profiles p
    cross join lateral (select greatest(p.app_seen_at, p.created_at,
                          (select max(day)::timestamptz from usage_daily d where d.user_id = p.id)) last) x
    where exists (select 1 from push_subs s where s.user_id = p.id)
      and p.username <> 'nobetci'
      and (case when test then p.role = 'admin'
                else p.nudge_on and not is_muted(p.mute, 'hepsi') and not is_muted(p.mute, 'hatirlat')
                     and (p.role = 'admin' or (p.status = 'active' and (p.expires_at is null or p.expires_at > now())))
                     and x.last < now() - interval '3 days'
                     and (p.nudge_at is null or p.nudge_at < now() - interval '4 days')
                     and (p.nudge_at is null or p.nudge_at < x.last or p.nudge_streak < 3) end)
  loop
    k := coalesce(u.nudge_idx, 0) % jsonb_array_length(j);
    t := j->k->>0;
    b := replace(replace(j->k->>1, '{ad}', coalesce(nullif(u.ad, ''), 'Müfettişim')),
                 '{gun}', greatest(3, floor(extract(epoch from now() - u.last) / 86400))::int::text);
    perform net.http_post(url := relay,
      body := jsonb_build_object('vapid', jsonb_build_object('private', vpriv, 'public', vpub), 'subs', u.subs,
        'payload', jsonb_build_object('title', t, 'body', left(b, 180), 'url', '/', 'tag', 'tmpro-ozledik')),
      headers := '{"Content-Type": "application/json"}'::jsonb);
    if not test then
      update profiles set nudge_idx = k + 1, nudge_at = now(),
             nudge_streak = case when u.nudge_at is null or u.nudge_at < u.last then 1 else u.nudge_streak + 1 end
      where id = u.id;
    else
      update profiles set nudge_idx = k + 1 where id = u.id;  -- her denemede sıradaki espri gelsin
    end if;
    sent := sent + 1;
  end loop;
  return sent;
end $$;
revoke all on function public.send_nudges(boolean) from public, anon, authenticated;
grant execute on function public.send_nudges(boolean) to service_role;

-- Zamanlama: hafta içi 12:30 Türkiye (09:30 UTC)
do $$ begin
  perform cron.unschedule('tmpro-ozledik');
exception when others then null; end $$;
select cron.schedule('tmpro-ozledik', '30 9 * * 1-5', 'select public.send_nudges(false)');

notify pgrst, 'reload schema';
