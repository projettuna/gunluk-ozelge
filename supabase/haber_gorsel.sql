-- TMPRO · Haberler zaman tüneli: haber fotoğrafı (kaynağın kendi görseli, bağlantı olarak). Tekrar çalıştırılabilir.
alter table public.news add column if not exists image text;
notify pgrst, 'reload schema';
