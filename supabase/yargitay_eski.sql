-- TMPRO · Eski Yargıtay kararları "yeni eklenen" sayılmasın. Tekrar çalıştırılabilir.
-- Karar arama servisi bazen yıllar önceki kararları da döndürüyor. Karar tarihi (meta, GG.AA.YYYY)
-- 1 yıldan eskiyse kayıt arşive girer: Son Eklenenler'de ve bildirimlerde görünmez, Yargıtay kutusunda durur.

create or replace function public.items_eski_karar() returns trigger
language plpgsql as $$
declare d date;
begin
  if new.tur = 'Yargıtay (Ceza)' and new.eklendi is not null and new.meta ~ '^\d{2}\.\d{2}\.\d{4}' then
    begin
      d := to_date(substr(new.meta, 1, 10), 'DD.MM.YYYY');
      if d < (now() - interval '1 year')::date then new.eklendi := null; end if;
    exception when others then null;
    end;
  end if;
  return new;
end $$;

drop trigger if exists items_eski_karar on public.items;
create trigger items_eski_karar before insert on public.items
  for each row execute function public.items_eski_karar();

-- Bugüne kadar "yeni" diye eklenmiş eski kararları arşive al
update public.items set eklendi = null
where tur = 'Yargıtay (Ceza)' and eklendi is not null and meta ~ '^\d{2}\.\d{2}\.\d{4}'
  and to_date(substr(meta, 1, 10), 'DD.MM.YYYY') < (now() - interval '1 year')::date;
