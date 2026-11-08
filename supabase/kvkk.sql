-- TMPRO: KVKK onayları (kullanım şartları + aydınlatma + yurt dışı aktarım açık rızası)
alter table public.profiles add column if not exists kvkk_v text;
alter table public.profiles add column if not exists kvkk_at timestamptz;
alter table public.profiles add column if not exists yurtdisi_riza boolean not null default false;

-- Her onayın kalıcı kaydı (ispat için; kullanıcı silinse de onay geçmişi tutulur)
create table if not exists public.consent_log (
  id bigserial primary key,
  user_id uuid,
  surum text not null,
  sartlar boolean not null,
  yurtdisi boolean not null,
  user_agent text,
  created_at timestamptz not null default now()
);
alter table public.consent_log enable row level security;
drop policy if exists "onay: kendini görür" on public.consent_log;
create policy "onay: kendini görür" on public.consent_log for select
  using (user_id = auth.uid() or exists (select 1 from profiles where id = auth.uid() and role = 'admin'));
grant select on public.consent_log to authenticated;

create or replace function public.accept_terms(v text, yd boolean, ua text default null) returns void
language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then raise exception 'oturum yok'; end if;
  insert into consent_log (user_id, surum, sartlar, yurtdisi, user_agent) values (auth.uid(), left(v, 20), true, yd, left(ua, 300));
  update profiles set kvkk_v = left(v, 20), kvkk_at = now(), yurtdisi_riza = yd where id = auth.uid();
end $$;
grant execute on function public.accept_terms(text, boolean, text) to authenticated;

-- Hukuki metinlerde gösterilecek veri sorumlusu / satıcı bilgileri (Yönetim → Ayarlar'dan doldurulur)
insert into public.settings (key, value) values ('veri_sorumlusu', ''), ('vs_adres', ''), ('vs_eposta', '')
on conflict (key) do nothing;
notify pgrst, 'reload schema';

-- Yöneticiye anlık bildirim: yeni kredi talebi ve yeni abonelik talebi
create or replace function public.notify_admins(title text, body text) returns void
language plpgsql security definer set search_path = public, extensions as $$
declare subs jsonb; vpriv text; vpub text; relay text;
begin
  select value into vpriv from private_settings where key = 'vapid_private';
  select value into vpub from private_settings where key = 'vapid_public';
  select value into relay from private_settings where key = 'push_relay';
  if vpriv is null or vpub is null or relay is null then return; end if;
  select jsonb_agg(jsonb_build_object('endpoint', s.endpoint, 'p256dh', s.p256dh, 'auth', s.auth)) into subs
  from push_subs s join profiles p on p.id = s.user_id where p.role = 'admin';
  if subs is null then return; end if;
  perform net.http_post(url := relay,
    body := jsonb_build_object('vapid', jsonb_build_object('private', vpriv, 'public', vpub), 'subs', subs,
      'payload', jsonb_build_object('title', title, 'body', left(body, 180), 'url', '/', 'tag', 'admin-' || extract(epoch from now())::bigint)),
    headers := '{"Content-Type": "application/json"}'::jsonb);
exception when others then raise warning 'notify_admins: %', sqlerrm;
end $$;
revoke execute on function public.notify_admins(text, text) from public, anon, authenticated;

create or replace function public.trg_credit_order() returns trigger
language plpgsql security definer set search_path = public as $$
declare nm text; pk text;
begin
  select coalesce(full_name, username) into nm from profiles where id = new.user_id;
  select ad into pk from ai_packages where code = new.code;
  perform notify_admins('Yeni kredi talebi', nm || ' · ' || coalesce(pk, new.code) || ' · ' || new.fiyat || ' TL. Açıklama: ' || upper(new.code || ' ' || nm));
  return new;
end $$;
drop trigger if exists credit_orders_notify on public.credit_orders;
create trigger credit_orders_notify after insert on public.credit_orders for each row execute function public.trg_credit_order();

create or replace function public.trg_new_member() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.status = 'pending' then
    perform notify_admins('Yeni abonelik talebi', coalesce(new.full_name, new.username) || ' (@' || new.username || ') ödeme bekliyor. Kod: ' || coalesce(new.pay_code, ''));
  end if;
  return new;
end $$;
drop trigger if exists profiles_new_notify on public.profiles;
create trigger profiles_new_notify after insert on public.profiles for each row execute function public.trg_new_member();

-- Türkiye sunucusundan Yargıtay ceza kararlarının alınması (yalnızca gizli anahtarı bilen betik yazabilir)
create extension if not exists pgcrypto with schema extensions;
insert into public.private_settings (key, value)
  values ('ingest_token', encode(extensions.gen_random_bytes(24), 'hex'))
on conflict (key) do nothing;

create or replace function public.ingest_items(token text, rows jsonb, seed boolean default false) returns int
language plpgsql security definer set search_path = public as $$
declare n int;
begin
  if token is null or token <> (select value from private_settings where key = 'ingest_token') then raise exception 'yetkisiz'; end if;
  with ins as (
    insert into items (tur, title, meta, url, ozet, metin, eklendi)
    select 'Yargıtay (Ceza)', left(r->>'title', 300), left(r->>'meta', 200), left(r->>'url', 500), left(r->>'ozet', 1200),
           left(r->>'metin', 200000), case when seed then null else now() end
    from jsonb_array_elements(rows) r
    where coalesce(r->>'title', '') <> '' and coalesce(r->>'url', '') like 'https://karararama.yargitay.gov.tr/%'
    on conflict (tur, url, title) do nothing
    returning 1)
  select count(*) into n from ins;
  return n;
end $$;
revoke execute on function public.ingest_items(text, jsonb, boolean) from public;
grant execute on function public.ingest_items(text, jsonb, boolean) to anon, authenticated;
notify pgrst, 'reload schema';
