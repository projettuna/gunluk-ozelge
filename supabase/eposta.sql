-- TMPRO · E-posta bildirimleri (kayıt, onay, ret, kredi). onay_bildirim.sql'den SONRA çalıştırın; tekrar çalıştırılabilir.
-- E-postaları GitHub Actions (ozelge.py) mevcut SMTP ayarlarıyla gönderir.

alter table public.profiles add column if not exists email text;
create table if not exists public.banned (
  id bigserial primary key,
  kind text not null check (kind in ('ip', 'email', 'phone', 'username')),
  value text not null,
  reason text,
  created_at timestamptz not null default now(),
  unique (kind, value)
);

create table if not exists public.mail_queue (
  id bigserial primary key,
  to_email text not null,
  subject text not null,
  body text not null,
  created_at timestamptz not null default now(),
  sent_at timestamptz,
  error text
);
alter table public.mail_queue enable row level security;  -- politika yok: yalnızca servis anahtarı okur/yazar

-- Kayıtta e-postayı da profile yaz (eski mantık aynen korunur)
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into profiles (id, username, full_name, phone, email, pay_code, role, status)
  values (new.id,
          lower(coalesce(new.raw_user_meta_data->>'username', split_part(new.email, '@', 1))),
          new.raw_user_meta_data->>'full_name',
          new.raw_user_meta_data->>'phone',
          nullif(lower(trim(new.raw_user_meta_data->>'email')), ''),
          'TM' || lpad((floor(random() * 900000) + 100000)::int::text, 6, '0'),
          case when exists (select 1 from profiles) then 'user' else 'admin' end,
          case when exists (select 1 from profiles) then 'pending' else 'active' end);
  return new;
end $$;

create or replace function public.queue_mail(addr text, subj text, body text) returns void
language plpgsql security definer set search_path = public as $$
begin
  if addr is null or addr !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then return; end if;
  insert into mail_queue (to_email, subject, body) values (addr, subj, body);
end $$;
revoke execute on function public.queue_mail(text, text, text) from public, anon, authenticated;

-- Kullanıcı kendi e-postasını güncelleyebilsin (Hesap ekranı)
create or replace function public.set_my_email(addr text) returns void
language plpgsql security definer set search_path = public as $$
begin
  if addr is not null and addr <> '' and addr !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then raise exception 'geçersiz e-posta'; end if;
  update profiles set email = nullif(lower(trim(addr)), '') where id = auth.uid();
end $$;
grant execute on function public.set_my_email(text) to authenticated;

-- Yeni talep: kullanıcıya ödeme bilgileri
create or replace function public.trg_new_member_mail() returns trigger
language plpgsql security definer set search_path = public as $$
declare s jsonb;
begin
  if new.status <> 'pending' then return new; end if;
  select jsonb_object_agg(key, value) into s from settings;
  perform queue_mail(new.email, 'TMPRO abonelik talebiniz alındı',
    'Merhaba ' || coalesce(new.full_name, new.username) || ',' || E'\n\n' ||
    'TMPRO abonelik talebiniz alındı. Hesabınızın açılması için aşağıdaki hesaba havale/EFT yapmanız yeterli:' || E'\n\n' ||
    'Tutar: ' || coalesce(s->>'fiyat', '149') || ' TL / ' || coalesce(s->>'sure_gun', '30') || ' gün' || E'\n' ||
    'Alıcı: ' || coalesce(s->>'alici', '') || E'\n' ||
    'IBAN: ' || coalesce(s->>'iban', '') || E'\n' ||
    'Açıklama: ' || coalesce(new.pay_code, new.username) || E'\n\n' ||
    'Açıklamaya yukarıdaki kodu yazmayı unutmayın; ödemeniz bu kodla eşleştirilir.' || E'\n' ||
    'Ödemeniz kontrol edilip onaylandığında size ayrıca e-posta göndereceğiz. Uygulamada beklemenize gerek yok.' || E'\n\n' ||
    'Kullanıcı adınız: ' || new.username || E'\n' ||
    'Adres: https://tmpro.tmproapp.workers.dev');
  return new;
end $$;
drop trigger if exists profiles_new_mail on public.profiles;
create trigger profiles_new_mail after insert on public.profiles for each row execute function public.trg_new_member_mail();

-- Onay / ret
create or replace function public.trg_member_status_mail() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.status = 'active' and (old.status is distinct from 'active' or new.expires_at is distinct from old.expires_at) and new.role <> 'admin' then
    perform queue_mail(new.email, 'TMPRO hesabınız açıldı ✓',
      'Merhaba ' || coalesce(new.full_name, new.username) || ',' || E'\n\n' ||
      'Ödemeniz onaylandı, TMPRO hesabınız kullanıma hazır.' ||
      case when new.expires_at is not null then E'\n' || 'Abonelik bitiş tarihi: ' || to_char(new.expires_at at time zone 'Europe/Istanbul', 'DD.MM.YYYY') else '' end || E'\n\n' ||
      'Giriş: https://tmpro.tmproapp.workers.dev' || E'\n' ||
      'Kullanıcı adınız: ' || new.username || E'\n\n' ||
      'Uygulama gibi kullanmak için siteyi açıp ana ekrana ekleyin:' || E'\n' ||
      '• iPhone (Safari): Paylaş düğmesi → Ana Ekrana Ekle' || E'\n' ||
      '• Android (Chrome): sağ üstte ⋮ → Ana ekrana ekle / Uygulamayı yükle' || E'\n' ||
      'Ardından uygulamayı ana ekrandaki simgeden açıp Bildirimler''i açabilirsiniz.');
  elsif new.status = 'rejected' and old.status is distinct from 'rejected'
        and not exists (select 1 from banned where kind = 'username' and value = new.username) then
    perform queue_mail(new.email, 'TMPRO abonelik talebiniz hakkında',
      'Merhaba ' || coalesce(new.full_name, new.username) || ',' || E'\n\n' ||
      'Ödemeniz talebinizle eşleştirilemediği için hesabınız açılamadı. Ödeme yaptıysanız açıklamaya ' ||
      coalesce(new.pay_code, new.username) || ' kodunu yazdığınızdan emin olun ve bu e-postayı yanıtlayın.');
  end if;
  return new;
end $$;
drop trigger if exists profiles_status_mail on public.profiles;
create trigger profiles_status_mail after update of status, expires_at on public.profiles
  for each row execute function public.trg_member_status_mail();

-- Kredi talebi: oluşturulunca ödeme bilgisi, sonuçlanınca bilgi
create or replace function public.trg_credit_mail() returns trigger
language plpgsql security definer set search_path = public as $$
declare p profiles; pk text; s jsonb;
begin
  select * into p from profiles where id = new.user_id;
  select ad into pk from ai_packages where code = new.code;
  if tg_op = 'INSERT' then
    select jsonb_object_agg(key, value) into s from settings;
    perform queue_mail(p.email, 'TMPRO kredi talebiniz alındı',
      coalesce(pk, new.code) || ' talebiniz alındı.' || E'\n\n' ||
      'Tutar: ' || new.fiyat || ' TL' || E'\n' || 'Alıcı: ' || coalesce(s->>'alici', '') || E'\n' ||
      'IBAN: ' || coalesce(s->>'iban', '') || E'\n' ||
      'Açıklama: ' || upper(new.code || ' ' || coalesce(p.full_name, p.username)) || E'\n\n' ||
      'Açıklamayı yazmazsanız krediniz yüklenemez. Onaylanınca e-posta ile bilgilendirileceksiniz.');
  elsif new.status <> old.status and new.status in ('approved', 'rejected') then
    perform queue_mail(p.email,
      case when new.status = 'approved' then 'TMPRO krediniz yüklendi ✓' else 'TMPRO kredi talebiniz hakkında' end,
      case when new.status = 'approved' then coalesce(pk, new.code) || ' hesabınıza tanımlandı. İyi çalışmalar.'
           else 'Ödemeniz kredi talebinizle eşleştirilemedi. Ödeme yaptıysanız bu e-postayı yanıtlayın.' end);
  end if;
  return new;
end $$;
drop trigger if exists credit_orders_mail on public.credit_orders;
create trigger credit_orders_mail after insert or update of status on public.credit_orders
  for each row execute function public.trg_credit_mail();

-- ================= Kullanıcı silme ve engelleme =================
alter table public.profiles add column if not exists last_ip text;

create table if not exists public.banned (
  id bigserial primary key,
  kind text not null check (kind in ('ip', 'email', 'phone', 'username')),
  value text not null,
  reason text,
  created_at timestamptz not null default now(),
  unique (kind, value)
);
alter table public.banned enable row level security;
drop policy if exists "engel: yönetici" on public.banned;
create policy "engel: yönetici" on public.banned for all using (is_admin()) with check (is_admin());

create or replace function public.req_ip() returns text
language sql stable as $$
  select nullif(trim(coalesce(
    (current_setting('request.headers', true)::json)->>'cf-connecting-ip',
    (current_setting('request.headers', true)::json)->>'x-real-ip',
    split_part((current_setting('request.headers', true)::json)->>'x-forwarded-for', ',', 1))), '');
$$;

create or replace function public.norm_phone(p text) returns text
language sql immutable as $$ select nullif(right(regexp_replace(coalesce(p, ''), '\D', '', 'g'), 10), '') $$;

-- Kayıttan önce: bu bilgilerle engellenmiş biri var mı?
create or replace function public.signup_check(u text, addr text, ph text) returns text
language sql stable security definer set search_path = public as $$
  select case
    when exists (select 1 from banned b where
         (b.kind = 'ip' and b.value = req_ip()) or
         (b.kind = 'username' and b.value = lower(trim(u))) or
         (b.kind = 'email' and b.value = lower(trim(addr))) or
         (b.kind = 'phone' and b.value = norm_phone(ph))) then 'banned'
    when exists (select 1 from profiles where username = lower(trim(u))) then 'taken'
    else 'ok' end;
$$;
grant execute on function public.signup_check(text, text, text) to anon, authenticated;

-- Her açılışta: IP kaydı + engel kontrolü
create or replace function public.touch_ip() returns boolean
language plpgsql security definer set search_path = public as $$
declare p profiles; ip text := req_ip();
begin
  select * into p from profiles where id = auth.uid();
  if p.id is null then return false; end if;
  if ip is not null then update profiles set last_ip = ip where id = p.id; end if;
  if p.role = 'admin' then return false; end if;
  return exists (select 1 from banned b where
    (b.kind = 'ip' and b.value = ip) or (b.kind = 'username' and b.value = p.username) or
    (b.kind = 'email' and b.value = p.email) or (b.kind = 'phone' and b.value = norm_phone(p.phone)));
end $$;
grant execute on function public.touch_ip() to authenticated;

-- Yönetici: engelle (IP, e-posta, telefon, kullanıcı adı) ve/veya sil
create or replace function public.admin_ban_delete(uid uuid, do_ban boolean, do_delete boolean) returns void
language plpgsql security definer set search_path = public, auth as $$
declare p profiles; my_ip text := req_ip();
begin
  if not is_admin() then raise exception 'yetkisiz'; end if;
  select * into p from profiles where id = uid;
  if p.id is null then return; end if;
  if p.role = 'admin' then raise exception 'Yönetici silinemez'; end if;
  if do_ban then
    insert into banned (kind, value, reason) values ('username', p.username, 'yönetici') on conflict do nothing;
    if p.email is not null then insert into banned (kind, value, reason) values ('email', p.email, 'yönetici') on conflict do nothing; end if;
    if norm_phone(p.phone) is not null then insert into banned (kind, value, reason) values ('phone', norm_phone(p.phone), 'yönetici') on conflict do nothing; end if;
    -- yöneticinin kendi IP'si asla engellenmez
    if p.last_ip is not null and p.last_ip is distinct from my_ip then
      insert into banned (kind, value, reason) values ('ip', p.last_ip, 'yönetici') on conflict do nothing;
    end if;
    update profiles set status = 'rejected' where id = uid;
  end if;
  if do_delete then delete from auth.users where id = uid; end if;
end $$;
grant execute on function public.admin_ban_delete(uuid, boolean, boolean) to authenticated;

-- Yargıtay kararları artık Adalet Bakanlığı Mevzuat sitesinin karar aramasından da gelebilir
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
    where coalesce(r->>'title', '') <> '' and (coalesce(r->>'url', '') like 'https://karararama.yargitay.gov.tr/%' or coalesce(r->>'url', '') like 'https://mevzuat.adalet.gov.tr/ictihat/%')
    on conflict (tur, url, title) do nothing
    returning 1)
  select count(*) into n from ins;
  return n;
end $$;
revoke execute on function public.ingest_items(text, jsonb, boolean) from public;
grant execute on function public.ingest_items(text, jsonb, boolean) to anon, authenticated;
notify pgrst, 'reload schema';
