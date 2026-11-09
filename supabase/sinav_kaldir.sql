-- TMPRO · Yeterlik sınavı paketi iptal edildi (2026-11-09): tablolar, fonksiyonlar ve paket kaldırılır. Tekrar çalıştırılabilir.
drop trigger if exists sinav_bildirim_notify on public.sinav_bildirim;
drop table if exists public.sinav_bildirim;
drop table if exists public.sinav_sorular;
drop function if exists public.trg_sinav_bildirim();
drop function if exists public.set_sinav(uuid, int);
drop function if exists public.has_sinav();

-- Kredi onayı eski (sınavsız) hâline döner
create or replace function public.decide_credit(oid bigint, ok boolean) returns void
language plpgsql security definer set search_path = public as $$
declare o credit_orders; pk ai_packages;
begin
  if not exists (select 1 from profiles where id = auth.uid() and role = 'admin') then raise exception 'yetkisiz'; end if;
  select * into o from credit_orders where id = oid and status = 'pending' for update; if o.id is null then return; end if;
  update credit_orders set status = case when ok then 'approved' else 'rejected' end, decided_at = now() where id = oid;
  if not ok then return; end if;
  select * into pk from ai_packages where code = o.code;
  if pk.gun is not null then
    update profiles set ai_sinirsiz_until = greatest(coalesce(ai_sinirsiz_until, now()), now()) + make_interval(days => pk.gun) where id = o.user_id;
  else
    update profiles set ai_credits = ai_credits + pk.adet where id = o.user_id;
  end if;
end $$;
grant execute on function public.decide_credit(bigint, boolean) to authenticated;

-- Bekleyen sınav talepleri reddedilir; paket, geçmiş talep kaydı yoksa silinir (varsa kayıt korunur, uygulamada zaten görünmez)
update public.credit_orders set status = 'rejected', decided_at = now() where code = 'SINAV' and status = 'pending';
delete from public.ai_packages where code = 'SINAV' and not exists (select 1 from public.credit_orders where code = 'SINAV');
alter table public.profiles drop column if exists sinav_until;

notify pgrst, 'reload schema';
