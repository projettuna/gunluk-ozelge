-- TMPRO · Onay bildirimleri: abonelik veya kredi onaylanınca kullanıcının telefonuna anlık bildirim.
-- (kvkk.sql'den sonra çalıştırın; tekrar çalıştırılabilir.)

create or replace function public.notify_user(uid uuid, title text, body text) returns void
language plpgsql security definer set search_path = public, extensions as $$
declare subs jsonb; vpriv text; vpub text; relay text;
begin
  select value into vpriv from private_settings where key = 'vapid_private';
  select value into vpub from private_settings where key = 'vapid_public';
  select value into relay from private_settings where key = 'push_relay';
  if vpriv is null or vpub is null or relay is null then return; end if;
  select jsonb_agg(jsonb_build_object('endpoint', endpoint, 'p256dh', p256dh, 'auth', auth)) into subs
  from push_subs where user_id = uid;
  if subs is null then return; end if;
  perform net.http_post(url := relay,
    body := jsonb_build_object('vapid', jsonb_build_object('private', vpriv, 'public', vpub), 'subs', subs,
      'payload', jsonb_build_object('title', title, 'body', left(body, 180), 'url', '/', 'tag', 'onay-' || extract(epoch from now())::bigint)),
    headers := '{"Content-Type": "application/json"}'::jsonb);
exception when others then raise warning 'notify_user: %', sqlerrm;
end $$;
revoke execute on function public.notify_user(uuid, text, text) from public, anon, authenticated;

-- Üyelik onaylanınca / yenilenince
create or replace function public.trg_member_approved() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.status = 'active' and (old.status is distinct from 'active' or new.expires_at is distinct from old.expires_at) then
    perform notify_user(new.id, 'Hesabınız açıldı ✓',
      'Ödemeniz onaylandı, TMPRO kullanıma hazır.' ||
      case when new.expires_at is not null then ' Bitiş: ' || to_char(new.expires_at at time zone 'Europe/Istanbul', 'DD.MM.YYYY') else '' end);
  elsif new.status = 'rejected' and old.status is distinct from 'rejected' then
    perform notify_user(new.id, 'Talebiniz onaylanmadı', 'Ödemeniz eşleştirilemedi. Ayrıntı için uygulamayı açın.');
  end if;
  return new;
end $$;
drop trigger if exists profiles_approved_notify on public.profiles;
create trigger profiles_approved_notify after update of status, expires_at on public.profiles
  for each row execute function public.trg_member_approved();

-- Kredi talebi sonuçlanınca
create or replace function public.trg_credit_decided() returns trigger
language plpgsql security definer set search_path = public as $$
declare pk text;
begin
  if new.status <> old.status then
    select ad into pk from ai_packages where code = new.code;
    if new.status = 'approved' then
      perform notify_user(new.user_id, 'Krediniz yüklendi ✓', coalesce(pk, new.code) || ' hesabınıza tanımlandı.');
    elsif new.status = 'rejected' then
      perform notify_user(new.user_id, 'Kredi talebi onaylanmadı', 'Ödemeniz eşleştirilemedi (açıklama kodunu kontrol edin).');
    end if;
  end if;
  return new;
end $$;
drop trigger if exists credit_orders_decided_notify on public.credit_orders;
create trigger credit_orders_decided_notify after update of status on public.credit_orders
  for each row execute function public.trg_credit_decided();
