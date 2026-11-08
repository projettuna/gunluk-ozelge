import sys, re
sys.path.insert(0, ".")
import metin, ozelge as o
tests = [
 



 ("https://gib.gov.tr/mevzuat/kanun/437/cbk/436", "CB Kararı", ""),

 ("https://www.resmigazete.gov.tr/eskiler/2026/11/20261108-2.htm", "Resmî Gazete", ""),
]
k = o.get_kararlar(2)
if k: tests.append((o.karar_link(k[0]["id"]), "Danıştay (VUK 359)", ""))
for u, t, m in tests:
    try:
        x = metin.text_for({"url": u, "tur": t, "meta": m})
        print("##", t, len(x)); print(x[:1200].replace("\n", " ⏎ ")); print(x[-200:].replace("\n", " ⏎ "))
    except Exception as e:
        print("##", t, "HATA", repr(e))
