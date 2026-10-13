"""Altin (ons, XAU/USD) fiyat bildirimi -> Telegram botu.

Iki kademe:
  1) Normal: son bildirimden bu yana fiyat ESIK_YUZDE kadar oynarsa bildirim (referans yeni fiyata kayar).
  2) Sert hareket: gun icinde (TSI gun basindan) SERT_YUZDE'nin her katinda yuksek oncelikli bildirim.

Durum durum.json dosyasinda tutulur (GitHub Actions her degisiklikte depoya geri yazar).
Ortam degiskenleri: TELEGRAM_TOKEN ve TELEGRAM_CHAT_ID (zorunlu), TEST=1 (deneme bildirimi gonderir, durumu degistirmez).
"""
import datetime as dt
import json
import os
import sys
import urllib.request

ESIK_YUZDE = 0.5
SERT_YUZDE = 2.5
GECE_SESSIZ = (0, 8)  # TSI 00:00-08:00 arasi normal bildirim yok (sert hareket yine gelir)
DURUM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "durum.json")
TSI = dt.timezone(dt.timedelta(hours=3))
UA = {"User-Agent": "altin-bildirim/1.0"}


def _json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.load(r)


def fiyat_al():
    """Spot XAU/USD; olmazsa PAXG (altina 1:1 bagli token)."""
    try:
        return float(_json("https://api.gold-api.com/price/XAU")["price"]), "gold-api (XAU/USD)"
    except Exception as e:
        print("gold-api hata:", e)
    t = _json("https://api.gateio.ws/api/v4/spot/tickers?currency_pair=PAXG_USDT")
    return float(t[0]["last"]), "Gate PAXG (yedek)"


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


def yz(x):
    """+%1,04 / −%1,02"""
    return ("+" if x >= 0 else "−") + f"%{abs(x):.2f}".replace(".", ",")


def para_isaret(x):
    return ("+" if x >= 0 else "−") + para(abs(x))


def tablo(satirlar):
    """Sabit genislikli tablo: rakamlar alt alta hizali."""
    return "<pre>" + "\n".join(_esc(f"{k:<10} {v}") for k, v in satirlar) + "</pre>"


def esikler(fiyat):
    return f"🎯 Sonraki eşik: ▲ {para(fiyat * (1 + ESIK_YUZDE / 100))} · ▼ {para(fiyat * (1 - ESIK_YUZDE / 100))}"


def mesaj_normal(fiyat, ref, ref_zaman, gun_deg, saat):
    deg = (fiyat / ref - 1) * 100
    bas = (f"🟢 <b>ALTIN YÜKSELDİ ▲ {yz(deg)}</b>" if deg > 0
           else f"🔴 <b>ALTIN DÜŞTÜ ▼ {yz(deg)}</b>")
    t = tablo([("Fiyat", para(fiyat)), ("Değişim", para_isaret(fiyat - ref)),
               ("Önceki", para(ref)), ("", f"({ref_zaman})"),
               ("Bugün", ("▲ " if gun_deg >= 0 else "▼ ") + yz(gun_deg))])
    return f"{bas}\n{t}\n{esikler(fiyat)}\n🕒 {saat} TSİ"


def mesaj_sert(fiyat, acilis, gun_deg, kat, saat):
    yon = "▲" if gun_deg > 0 else "▼"
    sonraki = (abs(kat) + 1) * SERT_YUZDE * (1 if gun_deg > 0 else -1)
    t = tablo([("Fiyat", para(fiyat)), ("Gün başı", para(acilis)), ("Fark", para_isaret(fiyat - acilis))])
    return (f"🚨 <b>SERT HAREKET – ALTIN {yon} {yz(gun_deg)} (bugün)</b>\n{t}\n"
            f"⚠️ Bir sonraki sert eşik: {yz(sonraki)} ({para(acilis * (1 + sonraki / 100))})\n🕒 {saat} TSİ")


def mesaj_test(fiyat, kaynak, ref, saat):
    t = tablo([("Fiyat", para(fiyat)), ("Kaynak", kaynak), ("Referans", para(ref))])
    return (f"🧪 <b>Altın bildirimi – deneme</b>\n{t}\n"
            f"📏 Kurallar: son bildirimden ±%{f'{ESIK_YUZDE:g}'.replace('.', ',')} → bildirim · "
            f"gün içinde ±%{f'{SERT_YUZDE:g}'.replace('.', ',')} katları → 🚨\n"
            f"{esikler(ref)}\n🕒 {saat} TSİ")


def piyasa_kapali(simdi_utc):
    # Altin piyasasi: Cuma ~21:00 UTC kapanir, Pazar ~22:00 UTC acilir.
    g, s = simdi_utc.weekday(), simdi_utc.hour  # Pzt=0 ... Paz=6
    return g == 5 or (g == 4 and s >= 21) or (g == 6 and s < 22)


def para(x):
    return f"{x:,.2f} $".replace(",", "X").replace(".", ",").replace("X", ".")


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
        ref = durum.get("ref", fiyat)
        bildir(mesaj_test(fiyat, kaynak, ref, saat), "deneme")
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
        gun_deg = (fiyat / durum["gun_acilis"] - 1) * 100
        bildir(mesaj_normal(fiyat, durum["ref"], durum.get("ref_zaman", "?"), gun_deg, saat),
               f"normal {deg:+.2f}%")
        durum.update(ref=fiyat, ref_zaman=saat)

    # 2) Sert hareket kademesi (gun ici)
    gun_deg = (fiyat / durum["gun_acilis"] - 1) * 100
    kat = int(abs(gun_deg) // SERT_YUZDE) * (1 if gun_deg > 0 else -1)
    onceki = durum.get("sert", 0)
    if kat != 0 and (abs(kat) > abs(onceki) or kat * onceki < 0):
        bildir(mesaj_sert(fiyat, durum["gun_acilis"], gun_deg, kat, saat), f"sert {gun_deg:+.2f}%")
        durum["sert"] = kat

    # Yalnizca durum degistiyse yaz (her 10 dk'da bir commit olmasin)
    if json.dumps(durum, sort_keys=True) != once:
        with open(DURUM, "w", encoding="utf-8") as f:
            json.dump(durum, f, ensure_ascii=False, indent=1)
    print("fiyat", fiyat, kaynak, "| ref", durum["ref"], "| gun %", round(gun_deg, 2))


if __name__ == "__main__":
    main()
