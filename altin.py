"""Altin (ons) fiyat bildirimi -> Telegram botu.

Iki kademe:
  1) Normal: son bildirimden bu yana fiyat ESIK_YUZDE kadar oynarsa bildirim (referans yeni fiyata kayar).
  2) Sert hareket: gun icinde (TSI gun basindan) SERT_YUZDE'nin her katinda yuksek oncelikli bildirim.

Tum rakamlar tek kaynaktan: Gate PAXG/USDT (ons altina 1:1 bagli token).
Durum durum.json dosyasinda tutulur (GitHub Actions her degisiklikte depoya geri yazar).
Ortam degiskenleri: TELEGRAM_TOKEN ve TELEGRAM_CHAT_ID (zorunlu), TEST=1 (deneme bildirimi gonderir, durumu degistirmez).
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.request

ESIK_YUZDE = 0.5
SERT_YUZDE = 2.5
GECE_SESSIZ = (0, 8)  # TSI 00:00-08:00 arasi normal bildirim yok (sert hareket yine gelir)
DURUM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "durum.json")
TSI = dt.timezone(dt.timedelta(hours=3))
UA = {"User-Agent": "altin-bildirim/1.0"}
GATE = "https://api.gateio.ws/api/v4/spot"


def _json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.load(r)


def fiyat_al():
    t = _json(f"{GATE}/tickers?currency_pair=PAXG_USDT")
    return float(t[0]["last"]), "PAXG (ons altına 1:1)"


ONS_GRAM = 31.1034768
_kur = []


def kur_al():
    """USD/TRY: BtcTurk -> OKX -> gunluk doviz servisi; hicbiri olmazsa None. Bir kez cekilir."""
    if _kur:
        return _kur[0]
    deger = None
    for url, oku in (("https://api.btcturk.com/api/v2/ticker?pairSymbol=USDTTRY", lambda d: d["data"][0]["last"]),
                     ("https://www.okx.com/api/v5/market/ticker?instId=USDT-TRY", lambda d: d["data"][0]["last"]),
                     ("https://open.er-api.com/v6/latest/USD", lambda d: d["rates"]["TRY"])):
        try:
            deger = float(oku(_json(url)))
            break
        except Exception as e:
            print("kur hata:", url.split("/")[2], e)
    _kur.append(deger)
    return deger


def gram_tl(fiyat):
    kur = kur_al()
    return None if kur is None else fiyat * kur / ONS_GRAM


def tl(x):
    return f"{x:,.0f} ₺".replace(",", ".")


def donemler(fiyat):
    """24 saat / 1 hafta / 1 ay / yilbasi: (baslangic, en dusuk, en yuksek). Mum alanlari: t, hacim, kapanis, yuksek, dusuk, acilis."""
    now = int(time.time())
    m15 = _json(f"{GATE}/candlesticks?currency_pair=PAXG_USDT&interval=15m&from={now - 24 * 3600}&to={now}")
    yb = int(dt.datetime(dt.datetime.now(TSI).year, 1, 1, tzinfo=dt.timezone.utc).timestamp())
    gun = _json(f"{GATE}/candlesticks?currency_pair=PAXG_USDT&interval=1d&from={yb}&to={now}")

    def aralik(mumlar):
        return min([float(m[4]) for m in mumlar] + [fiyat]), max([float(m[3]) for m in mumlar] + [fiyat])

    def gunluk(n):
        sinir = now - n * 86400
        secim = [m for m in gun if int(m[0]) > sinir]
        onceki = [m for m in gun if int(m[0]) <= sinir]
        return (float(onceki[-1][2]) if onceki else float(secim[0][5]),) + aralik(secim)

    return {"24 saat": (float(m15[0][5]),) + aralik(m15),
            "1 hafta": gunluk(7), "1 ay": gunluk(30),
            "Yılbaşı": (float(gun[0][5]),) + aralik(gun)}


def bildir(metin_html, ozet):
    """metin_html: Telegram HTML (b, pre). ozet: log icin kisa baslik."""
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        sys.exit("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID tanimli degil")
    govde = {"chat_id": chat, "text": metin_html, "parse_mode": "HTML"}
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=json.dumps(govde).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **UA})
    urllib.request.urlopen(req, timeout=20).read()
    print("bildirim gonderildi:", ozet)


# ---------- Mesaj bicimi ----------

def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def para(x):
    return f"{x:,.2f} $".replace(",", "X").replace(".", ",").replace("X", ".")


def yz(x):
    """+%1,04 / −%1,02"""
    return ("+" if x >= 0 else "−") + f"%{abs(x):.2f}".replace(".", ",")


def para_isaret(x):
    return ("+" if x >= 0 else "−") + para(abs(x))


def degisim(fiyat, bas):
    d = (fiyat / bas - 1) * 100
    return f"{'▲' if d >= 0 else '▼'} {para_isaret(fiyat - bas):<11} ({yz(d)})"


def tablo(ust, fiyat):
    """ust: mesaja ozel ilk satirlar; altina donem degisimleri ve araliklar eklenir."""
    satirlar = list(ust)
    try:
        d = donemler(fiyat)
        satirlar += [("", "")] + [(ad, degisim(fiyat, v[0])) for ad, v in d.items()]
        satirlar += [("", ""), ("Aralık", "en düşük – en yüksek")]
        for ad, anahtar in (("24 saat", "24 saat"), ("Haftalık", "1 hafta"), ("Aylık", "1 ay"), ("Yıllık", "Yılbaşı")):
            _, dus, yuk = d[anahtar]
            satirlar.append((ad, f"{para(dus)[:-2]} – {para(yuk)}"))
    except Exception as e:  # donem verisi alinamazsa bildirim yine gider
        print("donem verisi alinamadi:", e)
    g = gram_tl(fiyat)
    if g is not None:  # tablonun en sonunda
        satirlar += [("", ""), ("Gram TL", tl(g))]
    return "<pre>" + "\n".join(_esc(f"{k:<9} {v}".rstrip()) for k, v in satirlar) + "</pre>"


def mesaj_normal(fiyat, ref, ref_zaman, saat):
    deg = (fiyat / ref - 1) * 100
    bas = (f"🟢 <b>ALTIN YÜKSELDİ ▲ {yz(deg)}</b>" if deg > 0
           else f"🔴 <b>ALTIN DÜŞTÜ ▼ {yz(deg)}</b>")
    t = tablo([("Fiyat", para(fiyat)), ("Değişim", f"{degisim(fiyat, ref)}"), ("", f"son bildirim {ref_zaman}")], fiyat)
    return f"{bas}\n{t}\n🕒 {saat} TSİ"


def mesaj_sert(fiyat, acilis, gun_deg, kat, saat):
    yon = "▲" if gun_deg > 0 else "▼"
    sonraki = (abs(kat) + 1) * SERT_YUZDE * (1 if gun_deg > 0 else -1)
    t = tablo([("Fiyat", para(fiyat)), ("Gün başı", para(acilis)), ("Fark", degisim(fiyat, acilis))], fiyat)
    return (f"🚨 <b>SERT HAREKET – ALTIN {yon} {yz(gun_deg)} (bugün)</b>\n{t}\n"
            f"⚠️ Bir sonraki sert eşik: {yz(sonraki)} ({para(acilis * (1 + sonraki / 100))})\n🕒 {saat} TSİ")


def mesaj_test(fiyat, ref, saat):
    t = tablo([("Fiyat", para(fiyat))], fiyat)
    return (f"🧪 <b>Altın bildirimi – deneme</b>\n{t}\n"
            f"📏 Kurallar: son bildirimden ±%{f'{ESIK_YUZDE:g}'.replace('.', ',')} → bildirim · "
            f"gün içinde ±%{f'{SERT_YUZDE:g}'.replace('.', ',')} katları → 🚨 · "
            f"{GECE_SESSIZ[0]:02d}:00–{GECE_SESSIZ[1]:02d}:00 sessiz\n🕒 {saat} TSİ")


def mesaj_haftalik(fiyat, sayac, saat):
    g = gram_tl(fiyat)
    n, s = sayac.get("normal", 0), sayac.get("sert", 0)
    return (f"✅ <b>Altın bildirimi çalışıyor</b>\n"
            f"Geçen hafta: {n + s} bildirim ({n} normal, {s} sert)\n"
            f"Fiyat {para(fiyat)}" + (f" · Gram {tl(g)}" if g else "") + f"\n🕒 {saat} TSİ")


def piyasa_kapali(simdi_utc):
    # Altin piyasasi: Cuma ~21:00 UTC kapanir, Pazar ~22:00 UTC acilir.
    g, s = simdi_utc.weekday(), simdi_utc.hour  # Pzt=0 ... Paz=6
    return g == 5 or (g == 4 and s >= 21) or (g == 6 and s < 22)


def main():
    simdi = dt.datetime.now(dt.timezone.utc)
    test = os.environ.get("TEST", "").lower() in ("1", "true", "evet")
    if piyasa_kapali(simdi) and not test:
        print("piyasa kapali, atlandi")
        return

    fiyat, kaynak = fiyat_al()
    bugun = simdi.astimezone(TSI).strftime("%Y-%m-%d")
    saat = simdi.astimezone(TSI).strftime("%d.%m %H:%M")
    durum = json.load(open(DURUM, encoding="utf-8")) if os.path.exists(DURUM) else {}

    if test:
        bildir(mesaj_test(fiyat, durum.get("ref", fiyat), saat), "deneme")
        return

    once = json.dumps(durum, sort_keys=True)
    if "ref" not in durum:
        durum = {"ref": fiyat, "ref_zaman": saat}
        print("ilk calisma, referans:", fiyat)

    # Hatali veri korumasi: tek seferde %8'den buyuk sicrama -> veri supheli, atla
    if abs(fiyat / durum["ref"] - 1) * 100 > 8:
        print("supheli fiyat, atlandi:", fiyat, "ref:", durum["ref"])
        return

    if durum.get("gun") != bugun:
        durum.update(gun=bugun, gun_acilis=fiyat, sert=0)

    # 1) Normal kademe
    deg = (fiyat / durum["ref"] - 1) * 100
    sessiz = GECE_SESSIZ[0] <= simdi.astimezone(TSI).hour < GECE_SESSIZ[1]
    # Gece: referans degismez; sabah ilk kontrolde gece boyunca olan hareket tek bildirimle gelir
    if abs(deg) >= ESIK_YUZDE and not sessiz:
        bildir(mesaj_normal(fiyat, durum["ref"], durum.get("ref_zaman", "?"), saat), f"normal {deg:+.2f}%")
        durum.update(ref=fiyat, ref_zaman=saat)
        sayac = durum.setdefault("sayac", {})
        sayac["normal"] = sayac.get("normal", 0) + 1

    # 2) Sert hareket kademesi (gun ici)
    gun_deg = (fiyat / durum["gun_acilis"] - 1) * 100
    kat = int(abs(gun_deg) // SERT_YUZDE) * (1 if gun_deg > 0 else -1)
    onceki = durum.get("sert", 0)
    if kat != 0 and (abs(kat) > abs(onceki) or kat * onceki < 0):
        bildir(mesaj_sert(fiyat, durum["gun_acilis"], gun_deg, kat, saat), f"sert {gun_deg:+.2f}%")
        durum["sert"] = kat
        sayac = durum.setdefault("sayac", {})
        sayac["sert"] = sayac.get("sert", 0) + 1

    # 3) Haftalik "sistem calisiyor": Pazartesi 09:00 TSI sonrasi ilk kontrol, haftada bir
    yerel = simdi.astimezone(TSI)
    hafta = f"{yerel.isocalendar()[0]}-H{yerel.isocalendar()[1]:02d}"
    if yerel.weekday() == 0 and yerel.hour >= 9 and durum.get("kalp") != hafta:
        bildir(mesaj_haftalik(fiyat, durum.get("sayac", {}), saat), "haftalik")
        durum.update(kalp=hafta, sayac={})

    # Yalnizca durum degistiyse yaz (her kontrolde commit olmasin)
    if json.dumps(durum, sort_keys=True) != once:
        with open(DURUM, "w", encoding="utf-8") as f:
            json.dump(durum, f, ensure_ascii=False, indent=1)
    print("fiyat", fiyat, kaynak, "| ref", durum["ref"], "| gun %", round(gun_deg, 2))


if __name__ == "__main__":
    main()
