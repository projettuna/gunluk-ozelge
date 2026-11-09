-- TMPRO · Haberler uygulama içinde açılsın: haber özeti kolonu. Tekrar çalıştırılabilir.
alter table public.news add column if not exists ozet text;
notify pgrst, 'reload schema';
