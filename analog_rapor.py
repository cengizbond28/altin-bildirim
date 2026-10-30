"""Ons altın – benzer yıllar (analog) aylık e-posta raporu.

TradingView'deki "Ons Altın Benzer Yıllar (Analog)" göstergesiyle aynı yöntem ve aynı veri mantığı:
  - Bu yılın tamamlanmış aylarının yıl başından itibaren birikimli % yolu, başlangıç yılından
    (vars. 1971) bu yana her yılın aynı aylarıyla karşılaştırılır.
  - Fark (RMSE, puan) en küçük olan yıllar "en benzer" sayılır; en benzer N yılın kalan
    aylardaki ortalama seyri verilir.
Veri:
  - Ay sonu KAPANIŞ: Yahoo Finance GC=F (altın vadeli, 2000'den beri) → 12 ayı tam olan yıllar + bu yıl.
  - Eski yıllar: datasets/gold-prices (aylık ORTALAMA) → tabloda "*" ile işaretlenir.
  - Yahoo'ya ulaşılamazsa tamamen ortalama veriye geçer ve raporda belirtir.

Kullanım:
    python altin-benzer-yillar-rapor.py [--start 1971] [--top 3] [--rows 5] [--html cikti.html]
Çıktı (stdout): 1. satır "KONU: ...", ardından düz metin rapor. --html verilirse HTML gövde dosyaya yazılır.
"""
import argparse
import csv
import datetime as dt
import io
import json
import math
import statistics
import sys
import urllib.request

ORT_URL = "https://raw.githubusercontent.com/datasets/gold-prices/main/data/monthly.csv"
# Aylık (1mo) seride ay atlamaları olabiliyor; range=max ise günlüğü aylığa indiriyor. Bu yüzden
# açık tarih aralığıyla (period1/period2) GÜNLÜK veri alınıp ay sonu kapanışı hesaplanır.
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&period1=946684800&period2={son}"
AY = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def ortalama_fiyat():
    fiyat = {}
    for s in csv.DictReader(io.StringIO(_get(ORT_URL))):
        y, m = s["Date"].split("-")
        fiyat[(int(y), int(m))] = float(s["Price"])
    return fiyat


def yahoo_gunluk():
    """Yahoo GC=F günlük kapanışları: [(UTC zaman, kapanış), ...] eskiden yeniye; bugünkü (bitmemiş) gün dahil."""
    simdi = dt.datetime.now(dt.timezone.utc)
    res = json.loads(_get(YAHOO_URL.format(son=int(simdi.timestamp()))))["chart"]["result"][0]
    return [(dt.datetime.fromtimestamp(ts, dt.timezone.utc), c)
            for ts, c in sorted(zip(res["timestamp"], res["indicators"]["quote"][0]["close"])) if c is not None]


def kapanis_fiyat(gunluk=None):
    """Yahoo GC=F günlük kapanışlarından ay sonu kapanışı (her ayın son işlem günü); bitmemiş ay hariç."""
    simdi = dt.datetime.now(dt.timezone.utc)
    fiyat = {}
    for t, c in gunluk if gunluk is not None else yahoo_gunluk():
        if (t.year, t.month) == (simdi.year, simdi.month):
            continue  # bitmemiş ay
        fiyat[(t.year, t.month)] = c  # sıralı gezildiği için ayın son günü kalır
    return fiyat


def getiriler(fiyat, y):
    out = []
    for m in range(1, 13):
        onceki = (y - 1, 12) if m == 1 else (y, m - 1)
        if (y, m) in fiyat and onceki in fiyat and fiyat[onceki] > 0:
            out.append(fiyat[(y, m)] / fiyat[onceki] - 1.0)
        else:
            out.append(None)
    return out


def pct(x, d=1):
    return "-" if x is None else f"{x * 100:+.{d}f}".replace(".", ",")


def sayi(x):
    return f"{x:,.0f}".replace(",", ".")


def _kum(seri, n):
    p, out = 1.0, []
    for v in seri[:n]:
        p *= 1 + v
        out.append(p)
    return out


def _siralama(cur, k, tum):
    """tum: [(yıl, yıldız, 12 aylık getiri)] → bu yılın ilk k ayına benzerliğe göre sıralı liste."""
    cpath = _kum(cur, k)
    yillar = []
    for y, yildiz, r in tum:
        ppath = _kum(r, k)
        yillar.append({
            "yil": y, "yildiz": yildiz, "aylar": r,
            "rmse": math.sqrt(sum(((a - b) * 100) ** 2 for a, b in zip(ppath, cpath)) / k),
            "eslesme": sum(1 for a, c in zip(r[:k], cur[:k]) if a != 0 and (a > 0) == (c > 0)),
            "kalan": math.prod(1 + v for v in r[k:]) - 1 if k < 12 else None,
            "yilsonu": math.prod(1 + v for v in r) - 1,
        })
    yillar.sort(key=lambda d: d["rmse"])
    return yillar


def bant(baslangic, enb, k):
    """Bugünden (ay sonu kapanışı) itibaren en benzer yılların kalan ay hareketleri tekrarlanırsa
    her ay sonu için en düşük / en yüksek fiyat: [(ay indeksi, alt, üst), ...] (göstergedeki mor bant)."""
    yol, out = [baslangic] * len(enb), []
    for m in range(k, 12):
        yol = [p * (1 + d["aylar"][m]) for p, d in zip(yol, enb)]
        out.append((m, min(yol), max(yol)))
    return out


def isabet(tum, k, top):
    """Yöntemin geçmiş isabeti: her yıl yalnızca KENDİNDEN ÖNCEKİ yıllarla (en az 5) aynı yöntemle denenir;
    tahmin edilen kalan ay yönü gerçekleşenle karşılaştırılır. Göstergedeki "Geçmiş isabet" satırının aynısı."""
    ok = n = up = 0
    y1 = y2 = None
    for i, (t, _, rt) in enumerate(tum):
        once = tum[:i]
        if len(once) < 5:
            continue
        pt = _kum(rt, k)
        sirali = sorted(once, key=lambda z: sum(((a - b) * 100) ** 2 for a, b in zip(_kum(z[2], k), pt)))[:top]
        pr = math.prod(1 + sum(z[2][m] for z in sirali) / len(sirali) for m in range(k, 12))
        ac = math.prod(1 + rt[m] for m in range(k, 12))
        n += 1
        ok += (pr >= 1) == (ac >= 1)
        up += ac >= 1
        y1 = y1 or t
        y2 = t
    return {"ok": ok, "n": n, "up": up, "y1": y1, "y2": y2} if n else None


def hesapla(start, top, rows, gunluk=None):
    ort = ortalama_fiyat()
    try:
        gunluk = gunluk if gunluk is not None else yahoo_gunluk()
        kap = kapanis_fiyat(gunluk)
        kaynak = "kapanış"
    except Exception as e:  # ağ / engel
        gunluk, kap, kaynak = [], {}, f"ortalama (Yahoo'ya ulaşılamadı: {type(e).__name__})"

    cy = dt.datetime.now(dt.timezone.utc).year
    fiyat = kap or ort
    cur = getiriler(fiyat, cy)
    k = 0
    while k < 12 and cur[k] is not None:
        k += 1
    if k < 2:
        return {"cy": cy, "k": k, "yetersiz": True, "kaynak": kaynak}

    tum = []  # (yıl, yıldız, 12 aylık getiri) – kapanışta tam değilse ortalama veri (yıl içinde karışım yok)
    for y in range(start, cy):
        r, yildiz = getiriler(kap, y), False
        if any(v is None for v in r):
            r, yildiz = getiriler(ort, y), True
        if all(v is not None for v in r):
            tum.append((y, yildiz, r))
    yillar = _siralama(cur, k, tum)
    cpath = _kum(cur, k)

    enb = yillar[:top]
    kalanlar = [d["kalan"] for d in enb if d["kalan"] is not None]
    yuk = sum(1 for v in kalanlar if v >= 0)
    dus = len(kalanlar) - yuk
    yon = "yukarı" if dus == 0 and yuk else "aşağı" if yuk == 0 and dus else "karışık"
    proj = 1.0  # en benzer yılların kalan aylardaki ay ay ortalaması (göstergedeki kesikli çizgi)
    for m in range(k, 12):
        proj *= 1 + sum(d["aylar"][m] for d in enb) / len(enb)
    son = fiyat[(cy, k)]
    # Kalan aylarda en benzer yılların ay ay ortalaması ve medyanı (göstergedeki "⌀ Ort." ve "Orta (medyan)" satırları)
    ort_ay = [None] * 12
    med_ay = [None] * 12
    med_p = 1.0
    for m in range(k, 12):
        v = sorted(d["aylar"][m] for d in enb)
        ort_ay[m] = sum(v) / len(v)
        med_ay[m] = statistics.median(v)
        med_p *= 1 + med_ay[m]

    # Geçen ay: bir önceki ayın raporundaki (k-1 ay ile) bant, ay sonu kapanışı içinde kaldı mı?
    onceki = None
    if k >= 3 and (cy, k - 1) in fiyat:
        enb0 = _siralama(cur, k - 1, tum)[:top]
        _, lo0, hi0 = bant(fiyat[(cy, k - 1)], enb0, k - 1)[0]
        onceki = {"ay": AY[k - 1], "alt": lo0, "ust": hi0, "kapanis": son, "yillar": enb0,
                  "durum": 1 if son > hi0 else -1 if son < lo0 else 0,
                  "degisti": [d["yil"] for d in enb0] != [d["yil"] for d in enb]}

    return {
        "cy": cy, "k": k, "cur": cur, "ytd": cpath[-1] - 1, "yillar": yillar[:rows], "enb": enb,
        "yuk": yuk, "dus": dus, "yon": yon, "proj": proj - 1, "son": son, "hedef": son * proj,
        "start": start, "n": len(yillar), "kaynak": kaynak,
        "bant": bant(son, enb, k) if k < 12 else [], "isabet": isabet(tum, k, top) if k < 12 else None,
        "onceki": onceki, "gunluk": gunluk,
        "ort_ay": ort_ay, "med_ay": med_ay, "med_proj": med_p - 1, "med_hedef": son * med_p,
    }


def _etiketler(s):
    k = s["k"]
    return f"{AY[0]}–{AY[k - 1]}", (f"{AY[k]}–{AY[11]}" if k < 12 else "-")


def _not(s):
    return (f"Fark = yıl başından itibaren % yollar arası ortalama fark (küçük = daha benzer). "
            f"{s['n']} yıl karşılaştırıldı ({s['start']}–{s['cy'] - 1}). "
            f"Veri: {s['kaynak']} (Yahoo GC=F ay sonu kapanışı); * = eski yıl, aylık ortalama verisi (datasets/gold-prices). "
            "Bu bir istatistik özetidir, yatırım tavsiyesi değildir.")


def _yil(d):
    return f"{d['yil']}{'*' if d['yildiz'] else ''}"


def ek_satirlar(s):
    """Tablonun altındaki ek bilgiler: [(başlık, metin, durum)] – durum: 'iyi' / 'kotu' / 'bilgi'."""
    _, rt = _etiketler(s)
    out = []
    i = s.get("isabet")
    if i:
        out.append(("Geçmiş isabet",
                    f"{rt} yönü ({i['y1']}–{i['y2']}): {i['ok']}/{i['n']} = %{100 * i['ok'] / i['n']:.0f} · "
                    f"hep 'yukarı' deseydik: {i['up']}/{i['n']} = %{100 * i['up'] / i['n']:.0f}", "bilgi"))
    if s.get("bant"):
        out.append(("Senaryo bandı",
                    f"bugünden ({sayi(s['son'])} $): "
                    + " · ".join(f"{AY[m]} {sayi(lo)}–{sayi(hi)}" for m, lo, hi in s["bant"]) + " $", "bilgi"))
    o = s.get("onceki")
    if o:
        txt = (f"{o['ay']} kapanışı {sayi(o['kapanis'])} $ → "
               + ("bandın içinde kaldı ✓" if o["durum"] == 0 else
                  f"bandın {'ÜSTÜNDE' if o['durum'] > 0 else 'ALTINDA'} kaldı ⚠")
               + f" (bant {sayi(o['alt'])}–{sayi(o['ust'])} $)")
        if o["degisti"]:
            txt += (" · en benzer yıllar değişti: " + ", ".join(_yil(d) for d in o["yillar"])
                    + " → " + ", ".join(_yil(d) for d in s["enb"]))
        out.append(("Geçen ay", txt, "iyi" if o["durum"] == 0 else "kotu"))
    return out


def metin_rapor(s):
    cy, k = s["cy"], s["k"]
    if s.get("yetersiz"):
        return (f"KONU: Altın benzer yıllar – {cy}: henüz yeterli ay yok",
                f"{cy} için en az 2 tamamlanmış ay gerekiyor (şu an {k}). Rapor Mart başından itibaren gelir.")
    kt, rt = _etiketler(s)
    enb = s["enb"]
    yil_txt = lambda d: f"{d['yil']}{'*' if d['yildiz'] else ''}"
    konu = f"Altın benzer yıllar – {cy} {kt}: en benzer {yil_txt(enb[0])} · {rt} yön: {s['yon']}"
    satir = [
        f"Ons altın · benzer yıllar raporu ({cy} {kt}, {k} ay tamamlandı)",
        f"{cy} yıl başından beri: {pct(s['ytd'])}% · son ay kapanışı: {sayi(s['son'])} $",
        "",
        f"SONUÇ: En benzer {len(enb)} yıl ({', '.join(yil_txt(d) for d in enb)}) {rt}: "
        f"{s['yuk']} yükseldi, {s['dus']} düştü · ort. {pct(s['proj'])}% → ~{sayi(s['hedef'])} $ · yön: {s['yon']}",
        "",
        "Yıl    | " + " | ".join(AY) + " | Eşleşme | Fark | Yıl sonu",
        f"{cy}   | " + " | ".join(pct(v) if i < k else "·" for i, v in enumerate(s["cur"])) + " | – | – | ?",
    ]
    for j, d in enumerate(s["yillar"]):
        satir.append(f"{yil_txt(d):<6} | " + " | ".join(pct(v) for v in d["aylar"])
                     + f" | {d['eslesme']}/{k} | {d['rmse']:.1f}".replace(".", ",") + f" | {pct(d['yilsonu'])}")
        if j == len(enb) - 1 and k < 12:
            satir.append(f"Ort.{len(enb)}y | " + " | ".join(pct(v) if v is not None else "·" for v in s["ort_ay"])
                         + f" | {rt} {pct(s['proj'])}% | ~{sayi(s['hedef'])}")
            satir.append("Medyan | " + " | ".join(pct(v) if v is not None else "·" for v in s["med_ay"])
                         + f" | {rt} {pct(s['med_proj'])}% | ~{sayi(s['med_hedef'])}")
    satir += [""] + [f"{b}: {t}" for b, t, _ in ek_satirlar(s)]
    satir += ["", _not(s)]
    return "KONU: " + konu, "\n".join(satir)


def html_rapor(s):
    cy, k = s["cy"], s["k"]
    if s.get("yetersiz"):
        return f"<p>{cy} için en az 2 tamamlanmış ay gerekiyor (şu an {k}).</p>"
    kt, rt = _etiketler(s)
    # Gmail uyumu: yalnızca düz renk + bgcolor/background-color; opacity ve background kısaltması kullanılmaz
    # (Gmail bunları siliyor). Hücre yazıları koyu, zemin açık/orta ton → her durumda okunur.
    LAC = "#0d3b8c"                                   # başlık bandı (İş İlanları Bülteni ile aynı tarz)
    YES = ["#e8f5e9", "#c8e6c9", "#81c784"]           # artı: <%2, %2–5, ≥%5
    KIR = ["#ffebee", "#ffcdd2", "#e57373"]           # eksi
    GRI_BG, GRI_TX, MET = "#e0e0e0", "#757575", "#1b1b1b"
    YON_BG = {"yukarı": "#2e7d32", "aşağı": "#c62828"}.get(s["yon"], "#ef6c00")
    F = "font-family:Segoe UI,Arial,sans-serif;"

    def ton(v):
        a = abs(v) * 100
        i = 2 if a >= 5 else 1 if a >= 2 else 0
        return (YES if v > 0 else KIR)[i] if v != 0 else GRI_BG

    def td(icerik, bg=None, renk=MET, hiza="right", kalin=False, ek=""):
        b = f' bgcolor="{bg}"' if bg else ""
        st = (f"{F}padding:4px 6px;font-size:12px;text-align:{hiza};color:{renk};border:1px solid #ffffff;"
              + (f"background-color:{bg};" if bg else "") + ("font-weight:bold;" if kalin else "") + ek)
        return f'<td{b} style="{st}">{icerik}</td>'

    def hucre(v, ref=None, karsilastir=False):
        if v is None:
            return td("·", renk="#9e9e9e", hiza="center")
        if karsilastir:  # 2026 ile aynı yöndeyse 2026'nın tonu, değilse gri
            ayni = v != 0 and (v > 0) == (ref > 0)
            return td(pct(v), bg=ton(ref) if ayni else GRI_BG, renk=MET if ayni else GRI_TX)
        return td(pct(v), bg=ton(v))

    bas = (f'<tr>' + td("Yıl", bg="#37474f", renk="#ffffff", hiza="left", kalin=True)
           + "".join(td(a, bg="#37474f", renk="#ffffff", hiza="center", kalin=True) for a in AY)
           + "".join(td(x, bg="#37474f", renk="#ffffff", hiza="center", kalin=True) for x in ("Eşleşme", "Fark", "Yıl sonu"))
           + "</tr>")
    satirlar = [bas]
    satirlar.append("<tr>" + td(f"▶ {cy}", bg="#fff8e1", renk="#b8860b", hiza="left", kalin=True)
                    + "".join(hucre(v) if i < k else hucre(None) for i, v in enumerate(s["cur"]))
                    + td("–", hiza="center") + td("–", hiza="center") + td("?", hiza="center") + "</tr>")
    for j, d in enumerate(s["yillar"]):
        ust = j < len(s["enb"])
        satirlar.append(
            "<tr>" + td(f'{d["yil"]}{"*" if d["yildiz"] else ""}', bg="#e3ecfa" if ust else None,
                        hiza="left", kalin=ust)
            + "".join(hucre(v, s["cur"][i], i < k) for i, v in enumerate(d["aylar"]))
            + td(f'{d["eslesme"]}/{k}', hiza="center", kalin=ust)
            + td(f'{d["rmse"]:.1f}'.replace(".", ","), kalin=ust)
            + td(pct(d["yilsonu"]), kalin=ust) + "</tr>")
        if j == len(s["enb"]) - 1 and k < 12:
            for ad, vals, top_, hedef, kal in ((f'⌀ Ort. {len(s["enb"])} yıl', s["ort_ay"], s["proj"], s["hedef"], True),
                                               ("Orta (medyan)", s["med_ay"], s["med_proj"], s["med_hedef"], False)):
                rk = "#2e7d32" if top_ >= 0 else "#c62828"
                satirlar.append(
                    "<tr>" + td(ad, bg="#fff8e1", renk="#b8860b" if kal else "#6d6d6d", hiza="left", kalin=kal)
                    + "".join(td("·", renk="#9e9e9e", hiza="center") if v is None else td(pct(v), bg=ton(v), kalin=kal) for v in vals)
                    + td(f"{pct(top_)}% · {s['yon']} {s['yuk']}↑{s['dus']}↓" if kal else f"{pct(top_)}%",
                         renk=(YON_BG if kal else rk), hiza="center", kalin=kal, ek="white-space:nowrap;").replace("<td", '<td colspan="2"', 1)
                    + td(f"~{sayi(hedef)}", renk=rk, kalin=kal) + "</tr>")

    def kart(deger, etiket, renk):
        return (f'<td bgcolor="#ffffff" style="{F}background-color:#ffffff;border:1px solid #dfe3ea;'
                f'padding:10px 8px;text-align:center;">'
                f'<div style="{F}font-size:20px;font-weight:bold;color:{renk};">{deger}</div>'
                f'<div style="{F}font-size:12px;color:#444444;margin-top:2px;">{etiket}</div></td>')

    enb_txt = ", ".join(f'{d["yil"]}{"*" if d["yildiz"] else ""}' for d in s["enb"])
    kartlar = ('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:10px 0;"><tr>'
               + kart(f'{pct(s["ytd"])}%', f"{cy} yıl başından beri", "#c62828" if s["ytd"] < 0 else "#2e7d32")
               + kart(f'{s["enb"][0]["yil"]}{"*" if s["enb"][0]["yildiz"] else ""}', "En benzer yıl", LAC)
               + kart(s["yon"].capitalize(), f"{rt} yön", YON_BG)
               + kart(f'{pct(s["proj"])}%', f'~{sayi(s["hedef"])} $ ({rt} ort.)', "#c62828" if s["proj"] < 0 else "#2e7d32")
               + "</tr></table>")
    serit = (f'<table width="100%" cellpadding="0" cellspacing="0"><tr><td bgcolor="{YON_BG}" '
             f'style="{F}background-color:{YON_BG};color:#ffffff;padding:9px 12px;font-size:13px;">'
             f'<b>En benzer {len(s["enb"])} yıl ({enb_txt}) {rt}:</b> {s["yuk"]} yükseldi, {s["dus"]} düştü · '
             f'ort. {pct(s["proj"])}% → ~{sayi(s["hedef"])} $ · <b>yön: {s["yon"]}</b></td></tr></table>')
    baslik = (f'<table width="100%" cellpadding="0" cellspacing="0"><tr><td bgcolor="{LAC}" '
              f'style="{F}background-color:{LAC};color:#ffffff;padding:14px 16px;">'
              f'<div style="{F}font-size:20px;font-weight:bold;color:#ffffff;">Altın Benzer Yıllar</div>'
              f'<div style="{F}font-size:13px;color:#ffffff;margin-top:2px;">{cy} {kt} ({k} ay) · '
              f'son ay kapanışı {sayi(s["son"])} $ · {s["n"]} yıl karşılaştırıldı ({s["start"]}–{cy - 1})</div>'
              f'</td></tr></table>')
    EK_BG = {"bilgi": "#e3f2fd", "iyi": "#e8f5e9", "kotu": "#ffebee"}
    EK_SOL = {"bilgi": "#1565c0", "iyi": "#2e7d32", "kotu": "#c62828"}
    ekler = "".join(
        f'<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px;"><tr>'
        f'<td width="6" bgcolor="{EK_SOL[d]}" style="background-color:{EK_SOL[d]};"></td>'
        f'<td bgcolor="{EK_BG[d]}" style="{F}background-color:{EK_BG[d]};color:#1b1b1b;padding:7px 10px;font-size:12px;">'
        f'<b>{b}:</b> {t}</td></tr></table>'
        for b, t, d in ek_satirlar(s))
    tablo_bas = (f'<table width="100%" cellpadding="0" cellspacing="0"><tr><td bgcolor="#37474f" '
                 f'style="{F}background-color:#37474f;color:#ffffff;padding:8px 12px;font-size:14px;font-weight:bold;">'
                 f'Ay ay % değişim · en benzer {len(s["yillar"])} yıl</td></tr></table>')
    return (f'<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#f4f6fa" style="background-color:#f4f6fa;">'
            f'<tr><td align="center" style="padding:12px 6px;">'
            f'<table width="760" cellpadding="0" cellspacing="0" style="max-width:760px;width:100%;"><tr><td>'
            f"{baslik}{kartlar}{tablo_bas}"
            f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{"".join(satirlar)}</table>'
            f"{ekler}"
            f'<p style="{F}color:#666666;font-size:11px;margin:8px 2px;">Renk: 2026 ile aynı yönde giden aylar 2026\'nın '
            f'tonunda, ters yöndekiler gri; koyu ton = büyük hareket (≥%5). {_not(s)}</p>'
            f"</td></tr></table></td></tr></table>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1971)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--rows", type=int, default=5)
    ap.add_argument("--html")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    s = hesapla(a.start, a.top, a.rows)
    konu, govde = metin_rapor(s)
    print(konu)
    print(govde)
    if a.html:
        with open(a.html, "w", encoding="utf-8") as f:
            f.write(html_rapor(s))


if __name__ == "__main__":
    main()
