-- TMPRO · Davet et, 1 ay kazan. Üye kendi arkadaş kodunu davet kodu olarak paylaşır; bu kodla kaydolan kişinin
-- aboneliği onaylanınca davet edenin aboneliğine 30 gün eklenir (süresiz hesaplara eklenmez). Tekrar çalıştırılabilir.
alter table public.profiles add column if not exists referred_by uuid references public.profiles(id) on delete set null;
alter table public.profiles add column if not exists referral_rewarded boolean not null default false;

-- Yeni üye, onay beklerken davet kodunu bir kez girebilir
create or replace function public.set_referrer(code text) returns text
language plpgsql security definer set search_path = public as $$
declare inv uuid; me profiles;
begin
  select * into me from profiles where id = auth.uid();
  if me.id is null then return 'yok'; end if;
  if me.referred_by is not null then return 'zaten'; end if;
  if me.status = 'active' and me.created_at < now() - interval '1 day' then return 'gec'; end if;
  select id into inv from profiles where friend_code = upper(trim(coalesce(code, '')));
  if inv is null then return 'bulunamadi'; end if;
  if inv = me.id then return 'kendin'; end if;
  update profiles set referred_by = inv where id = me.id;
  return 'ok';
end $$;
grant execute on function public.set_referrer(text) to authenticated;

-- Kaç kişi davetimle katıldı (onaylanan)
create or replace function public.my_referrals() returns json
language sql stable security definer set search_path = public as $$
  select json_build_object('katilan', count(*) filter (where referral_rewarded), 'bekleyen', count(*) filter (where not referral_rewarded and status = 'pending'))
  from profiles where referred_by = auth.uid();
$$;
grant execute on function public.my_referrals() to authenticated;

-- Hediye gün eklenirken davet edene "hesabınız açıldı" bildirimi ve e-postası gitmesin
create or replace function public.trg_member_approved() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if current_setting('tmpro.hediye', true) = '1' then return new; end if;  -- davet hediyesi: "hesabınız açıldı" bildirimi/e-postası gitmesin
  if new.status = 'active' and (old.status is distinct from 'active' or new.expires_at is distinct from old.expires_at) then
    perform notify_user(new.id, 'Hesabınız açıldı ✓',
      'Ödemeniz onaylandı, TMPRO kullanıma hazır.' ||
      case when new.expires_at is not null then ' Bitiş: ' || to_char(new.expires_at at time zone 'Europe/Istanbul', 'DD.MM.YYYY') else '' end);
  elsif new.status = 'rejected' and old.status is distinct from 'rejected' then
    perform notify_user(new.id, 'Talebiniz onaylanmadı', 'Ödemeniz eşleştirilemedi. Ayrıntı için uygulamayı açın.');
  end if;
  return new;
end $$;

create or replace function public.trg_member_status_mail() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if current_setting('tmpro.hediye', true) = '1' then return new; end if;  -- davet hediyesi: "hesabınız açıldı" bildirimi/e-postası gitmesin
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

create or replace function public.trg_referral_reward() returns trigger
language plpgsql security definer set search_path = public as $$
declare inv profiles;
begin
  if new.status = 'active' and old.status is distinct from 'active' and new.referred_by is not null and not new.referral_rewarded then
    update profiles set referral_rewarded = true where id = new.id;
    select * into inv from profiles where id = new.referred_by;
    if inv.id is not null and inv.expires_at is not null and inv.status = 'active' then
      perform set_config('tmpro.hediye', '1', true);
      update profiles set expires_at = greatest(expires_at, now()) + interval '30 days' where id = inv.id;
      perform set_config('tmpro.hediye', '', true);
      perform notify_user(inv.id, '🎁 1 ay hediye', 'Davet ettiğiniz üye aramıza katıldı. Aboneliğinize 30 gün eklendi. Teşekkürler!');
    elsif inv.id is not null then
      perform notify_user(inv.id, '🎉 Davetiniz katıldı', 'Davet ettiğiniz üye aramıza katıldı. Teşekkürler!');
    end if;
  end if;
  return new;
end $$;
drop trigger if exists profiles_referral_reward on public.profiles;
create trigger profiles_referral_reward after update of status on public.profiles
  for each row execute function public.trg_referral_reward();
notify pgrst, 'reload schema';
