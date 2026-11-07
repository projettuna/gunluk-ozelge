import re, json
from urllib.request import Request, urlopen
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
def get(url, t=60):
    with urlopen(Request(url, headers={"User-Agent": UA}), timeout=t) as r:
        return r.read().decode("utf-8", "replace")
js = get("https://kararlarbilgibankasi.anayasa.gov.tr/kbb/assets/index-DJw1O8y-.js")
i = js.find("cm=()=>"); print("CM", js[i:i+900])
for m in re.finditer(r"cm\(\)", js):
    print("CMUSE", js[max(0, m.start()-400):m.start()+300]); 
for m in list(re.finditer(r"RS\(", js))[:3]:
    print("RSUSE", js[max(0, m.start()-1500):m.start()+300])
i = js.find("qt=");  print("QT", js[i:i+1200] if i>=0 else None)
for m in list(re.finditer(r"interceptors", js))[:3]:
    print("INT", js[max(0, m.start()-200):m.start()+900])
