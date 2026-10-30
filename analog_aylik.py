"""Altın benzer yıllar (analog) — aylık Telegram özeti + canlı karne.

Her ayın 1'inde (GitHub Actions) çalışır:
  1) Karne: analog_karne.csv'de sonucu boş olan geçmiş ay tahminlerini gerçek ay sonu kapanışıyla doldurur
     (mor bant içinde mi, mavi bant içinde mi, yön tuttu mu, hedeften fark).
  2) Yeni ay: en benzer 3 yılı, ay sonu hedefini (ortalama), mor bandı (en iyi–en kötü) ve
     mavi bandı (medyan ± MAD) hesaplar, karneye yeni satır olarak yazar.
  3) Özeti Telegram'a gönderir.
Hesap analog_rapor.py (Desktop\\trading\\betikler\\altin-benzer-yillar-rapor.py kopyası) ile yapılır:
Yahoo GC=F ay sonu kapanışı + 2000 öncesi yıllar için aylık ortalama veri (* ile işaretli).

Ortam değişkenleri: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID (zorunlu; YAZDIR=1 ise gerekmez),
TEST=1 (deneme mesajı gönderir, karneyi değiştirmez), YAZDIR=1 (mesajı göndermez, ekrana basar;
TEST=1 ile birlikte kuru çalıştırma olur).
Yalnızca istatistik özetidir; yatırım tavsiyesi değildir.
"""
import csv
import datetime as dt
import json
import os
import statistics
import sys
import urllib.request

import analog_rapor as r

KLASOR = os.path.dirname(os.path.abspath(__file__))
KARNE = os.path.join(KLASOR, "analog_karne.csv")
# Ay sonu kapanışları depoda saklanır; her ay yalnız eksik (yeni) aylar çekilir: önce Yahoo GC=F, olmazsa Gate PAXG (spot).
KAPANISLAR = os.path.join(KLASOR, "kapanislar.csv")
GATE = "https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair=PAXG_USDT&interval=1d&from={bas}&to={son}"
ILK_AY = (2000, 1)
ALANLAR = ["tahmin_tarihi", "ay", "baz_kapanis", "yillar", "hedef", "mor_alt", "mor_ust", "mavi_alt", "mavi_ust",
           "gercek_kapanis", "mor_sonuc", "mavi_sonuc", "yon_tuttu", "hedef_fark_yuzde"]
AY_TAM = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def karne_oku():
    if not os.path.exists(KARNE):
        return []
    with open(KARNE, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def karne_yaz(satirlar):
    with open(KARNE, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ALANLAR, lineterminator="\n")
        w.writeheader()
        w.writerows(satirlar)


def kapanis_oku():
    """{(yıl, ay): (kapanış, kaynak)}"""
    if not os.path.exists(KAPANISLAR):
        return {}
    with open(KAPANISLAR, encoding="utf-8", newline="") as f:
        return {tuple(map(int, s["ay"].split("-"))): (float(s["kapanis"]), s["kaynak"]) for s in csv.DictReader(f)}


def kapanis_yaz(kap):
    with open(KAPANISLAR, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")  # git'teki dosyayla aynı satır sonu; gereksiz commit olmasın
        w.writerow(["ay", "kapanis", "kaynak"])
        for (y, m), (c, k) in sorted(kap.items()):
            w.writerow([f"{y}-{m:02d}", f"{c:.2f}", k])


def _sonraki_ay(a):
    y, m = a
    return (y + 1, 1) if m == 12 else (y, m + 1)


def _aylar(bas, son):
    while bas <= son:
        yield bas
        bas = _sonraki_ay(bas)


def gate_ay_sonu(eksik):
    """Gate PAXG/USDT günlük mumlarından ay sonu kapanışı (mum: t, hacim, kapanış, ...); bitmemiş ay hariç."""
    simdi = dt.datetime.now(dt.timezone.utc)
    bas = int(dt.datetime(*min(eksik), 1, tzinfo=dt.timezone.utc).timestamp())
    req = urllib.request.Request(GATE.format(bas=bas, son=int(simdi.timestamp())), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as f:
        mumlar = json.loads(f.read().decode("utf-8"))
    out = {}
    for mum in sorted(mumlar, key=lambda x: int(x[0])):
        t = dt.datetime.fromtimestamp(int(mum[0]), dt.timezone.utc)
        if (t.year, t.month) != (simdi.year, simdi.month):
            out[(t.year, t.month)] = float(mum[2])  # sıralı gezildiği için ayın son günü kalır
    return out


def kapanislari_guncelle():
    """Kapanış dosyasını tamamlanmış son aya kadar tamamlar; {(yıl, ay): kapanış} ve kullanılan kaynakları döndürür."""
    kap = kapanis_oku()
    simdi = dt.datetime.now(dt.timezone.utc)
    son_ay = (simdi.year - 1, 12) if simdi.month == 1 else (simdi.year, simdi.month - 1)
    # Yalnız dosyadaki son aydan sonrası aranır (Yahoo 2000-08'den başlıyor; eski boşluklar her ay yeniden denenmesin)
    eksik = list(_aylar(_sonraki_ay(max(kap)) if kap else ILK_AY, son_ay))
    eksik_ilk = len(kap)
    if eksik:
        try:
            yahoo = r.kapanis_fiyat(r.yahoo_gunluk())
            kap.update({a: (yahoo[a], "yahoo") for a in eksik if a in yahoo})
        except Exception as e:
            print("Yahoo'ya ulasilamadi:", type(e).__name__, e)
        eksik = [a for a in eksik if a not in kap]
    if eksik:
        try:
            gate = gate_ay_sonu(eksik)
            kap.update({a: (gate[a], "gate-paxg") for a in eksik if a in gate})
        except Exception as e:
            print("Gate'e ulasilamadi:", type(e).__name__, e)
    if son_ay not in kap:
        sys.exit(f"{son_ay[0]}-{son_ay[1]:02d} kapanisi hicbir kaynaktan alinamadi; yarin (2'si) tekrar denenecek")
    if eksik_ilk != len(kap):  # yalnız yeni kapanış eklendiyse yaz
        kapanis_yaz(kap)
    return {a: c for a, (c, _) in kap.items()}, {k for a, (_, k) in kap.items() if a[0] >= son_ay[0]}


def _konum(x, lo, hi):
    return "üstünde" if x > hi else "altında" if x < lo else "içinde"


def puanla(satirlar, kapanis):
    """Sonucu boş olan ve ayı kapanmış tahminleri gerçek kapanışla doldurur; doldurulan satırları döndürür."""
    yeni = []
    for s in satirlar:
        if s["gercek_kapanis"]:
            continue
        y, m = map(int, s["ay"].split("-"))
        if (y, m) not in kapanis:
            continue
        g, baz, hedef = kapanis[(y, m)], float(s["baz_kapanis"]), float(s["hedef"])
        s["gercek_kapanis"] = f"{g:.1f}"
        s["mor_sonuc"] = _konum(g, float(s["mor_alt"]), float(s["mor_ust"]))
        s["mavi_sonuc"] = _konum(g, float(s["mavi_alt"]), float(s["mavi_ust"]))
        s["yon_tuttu"] = "evet" if (g >= baz) == (hedef >= baz) else "hayır"
        s["hedef_fark_yuzde"] = f"{(g / hedef - 1) * 100:.2f}"
        yeni.append(s)
    return yeni


def tahmin(s):
    """Bu ayın (k. ay, 0 tabanlı) ay sonu tahmini: hedef + mor bant + mavi bant."""
    k, son, enb = s["k"], s["son"], s["enb"]
    yollar = [son * (1 + d["aylar"][k]) for d in enb]
    med = statistics.median(yollar)
    mad = statistics.median(abs(v - med) for v in yollar)
    _, mor_alt, mor_ust = s["bant"][0]
    return {
        "tahmin_tarihi": dt.date.today().isoformat(), "ay": f"{s['cy']}-{k + 1:02d}", "baz_kapanis": f"{son:.1f}",
        "yillar": " ".join(r._yil(d) for d in enb), "hedef": f"{son * (1 + s['ort_ay'][k]):.1f}",
        "mor_alt": f"{mor_alt:.1f}", "mor_ust": f"{mor_ust:.1f}", "mavi_alt": f"{med - mad:.1f}", "mavi_ust": f"{med + mad:.1f}",
        **{a: "" for a in ALANLAR[9:]},
    }


def _ay_adi(ay):
    y, m = map(int, ay.split("-"))
    return f"{AY_TAM[m - 1]} {y}"


def _esc(x):
    return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _isaret(sonuc):
    return "✓ içinde" if sonuc == "içinde" else f"⚠ {sonuc}"


def mesaj(s, yeni_satir, puanlanan, satirlar, test):
    p = []
    if test:
        p.append("🧪 <b>DENEME</b> (karne değişmedi)")
    for g in puanlanan:
        fark = float(g["hedef_fark_yuzde"])
        p.append(f"<b>📋 {_ay_adi(g['ay'])} karnesi</b>")
        p.append("<pre>" + _esc("\n".join([
            f"Kapanış   {r.sayi(float(g['gercek_kapanis']))} $",
            f"Hedef     {r.sayi(float(g['hedef']))} $  (fark {r.pct(fark / 100)}%)",
            f"Mor bant  {r.sayi(float(g['mor_alt']))}–{r.sayi(float(g['mor_ust']))}  {_isaret(g['mor_sonuc'])}",
            f"Mavi bant {r.sayi(float(g['mavi_alt']))}–{r.sayi(float(g['mavi_ust']))}  {_isaret(g['mavi_sonuc'])}",
            f"Yön       {'✓ tuttu' if g['yon_tuttu'] == 'evet' else '✗ tutmadı'}",
        ])) + "</pre>")

    if yeni_satir:
        t, k = yeni_satir, s["k"]
        hedef, son = float(t["hedef"]), s["son"]
        p.append(f"<b>📐 Altın benzer yıllar — {_ay_adi(t['ay'])}</b>")
        p.append("<pre>" + _esc("\n".join([
            f"Benzer yıllar  {', '.join(r._yil(d) for d in s['enb'])}",
            f"Başlangıç      {r.sayi(son)} $ ({AY_TAM[k - 1]} kapanışı)",
            f"Ay sonu hedefi {r.sayi(hedef)} $ ({r.pct(hedef / son - 1)}%)",
            f"Mor bant       {r.sayi(float(t['mor_alt']))}–{r.sayi(float(t['mor_ust']))} $",
            f"Mavi bant      {r.sayi(float(t['mavi_alt']))}–{r.sayi(float(t['mavi_ust']))} $",
            f"Yıl sonu (ort) {r.sayi(s['hedef'])} $ ({r.pct(s['proj'])}%)",
        ])) + "</pre>")
        i = s.get("isabet")
        if i:
            p.append(f"Güven: düşük · geçmiş yön isabeti %{100 * i['ok'] / i['n']:.0f} "
                     f"(hep 'yukarı' deseydik %{100 * i['up'] / i['n']:.0f})")
    elif not test:
        p.append(f"<b>📐 Altın benzer yıllar</b>\n{s['cy']} için yeni tahmin yok (en az 2 tamamlanmış ay gerekir); Mart başında devam eder.")

    bitmis = [x for x in satirlar if x["gercek_kapanis"]]
    if bitmis:
        n = len(bitmis)
        mor = sum(x["mor_sonuc"] == "içinde" for x in bitmis)
        mavi = sum(x["mavi_sonuc"] == "içinde" for x in bitmis)
        yon = sum(x["yon_tuttu"] == "evet" for x in bitmis)
        p.append(f"🗂 Canlı karne ({n} ay): mor bant {mor}/{n} · mavi bant {mavi}/{n} · yön {yon}/{n}")
    if s.get("kaynak_uyari"):
        p.append("⚠️ <b>Yahoo 2 aydır çalışmıyor</b>: son iki kapanış Gate PAXG yedeğinden (spot, ~%0,5 düşük). "
                 "Veri kaynağı kontrol edilmeli.")
    p.append(f"<i>* = 2000 öncesi, aylık ortalama veri · {s.get('kaynak_notu', 'Yahoo GC=F')} · yatırım tavsiyesi değildir</i>")
    return "\n\n".join(p)


def gonder(metin):
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        sys.exit("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID tanimli degil")
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=json.dumps({"chat_id": chat, "text": metin, "parse_mode": "HTML"}).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    urllib.request.urlopen(req, timeout=20).read()
    print("mesaj gonderildi")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    test, yazdir = os.environ.get("TEST") == "1", os.environ.get("YAZDIR") == "1"
    kapanis, kaynaklar = kapanislari_guncelle()
    # hesapla() günlük seri bekler; her ay için tek "gün" (ayın 15'i) verilince ay sonu kapanışı aynen kalır
    gunluk = [(dt.datetime(y, m, 15, tzinfo=dt.timezone.utc), c) for (y, m), c in sorted(kapanis.items())]
    s = r.hesapla(1971, 3, 5, gunluk=gunluk)
    s["kaynak_notu"] = "Yahoo GC=F" + (" + Gate PAXG (yedek)" if "gate-paxg" in kaynaklar else "")
    son_iki = [k for _, (_, k) in sorted(kapanis_oku().items())[-2:]]
    s["kaynak_uyari"] = son_iki == ["gate-paxg", "gate-paxg"]

    satirlar = karne_oku()
    puanlanan = puanla(satirlar, kapanis)
    yeni = None
    if not s.get("yetersiz") and s["k"] < 12:
        yeni = tahmin(s)
        if any(x["ay"] == yeni["ay"] for x in satirlar):
            if not (test or yazdir):
                print(f"{yeni['ay']} tahmini zaten kayıtlı; bu ay mesaj gönderildi, çıkılıyor")
                return
        else:
            satirlar.append(yeni)

    metin = mesaj(s, yeni, puanlanan, satirlar, test)
    if yazdir:
        print(metin)
    else:
        gonder(metin)
    if not test:
        karne_yaz(satirlar)


if __name__ == "__main__":
    main()
