import os
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs

BASE_URL = "https://bayi.yasarteknik.com.tr"

MUSTERI_KODU = os.environ.get("YASAR_KULLANICI_ADI")
KULLANICI_KODU = os.environ.get("YASAR_KULLANICI_KODU")
SIFRE = os.environ.get("YASAR_SIFRE")

if not MUSTERI_KODU or not KULLANICI_KODU or not SIFRE:
    raise Exception("GitHub Secrets eksik!")


session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
})


def giris_yap():
    session.cookies.clear()

    r = session.get(
        f"{BASE_URL}/Login.asp",
        timeout=30
    )
    r.raise_for_status()

    login = session.post(
        f"{BASE_URL}/ajax/Login.asp",
        data={
            "KullaniciAdi": MUSTERI_KODU,
            "KullaniciKodu": KULLANICI_KODU,
            "Sifre": SIFRE
        },
        headers={
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/Login.asp",
            "X-Requested-With": "XMLHttpRequest"
        },
        timeout=30,
        allow_redirects=False
    )

    if login.status_code != 200 or login.text.strip() != "1":
        raise Exception(
            "Yaşar Teknik girişi başarısız!"
        )

    print("GİRİŞ BAŞARILI")


def getir(url, deneme=5):
    son_hata = None

    for sira in range(1, deneme + 1):
        try:
            r = session.get(
                url,
                timeout=45,
                allow_redirects=True
            )

            if "login.asp" in r.url.lower():
                print(
                    "Oturum düştü, yeniden giriş yapılıyor..."
                )
                giris_yap()
                time.sleep(1)
                continue

            r.raise_for_status()
            return r

        except Exception as e:
            son_hata = e

            print(
                f"İstek hatası {sira}/{deneme}: {e}"
            )

            if sira < deneme:
                try:
                    giris_yap()
                except Exception:
                    pass

                time.sleep(sira * 2)

    raise son_hata


# ============================================================
# GİRİŞ
# ============================================================

giris_yap()


# ============================================================
# ANA ÜRÜN SAYFASINI AÇ
# ============================================================

ana_url = (
    f"{BASE_URL}/YeniSiparisGir.asp"
    "?FView=list"
    "&FKatID="
    "&sayfa=1"
    "&FAdi="
    "&F=Ara"
    "&Sirala=Yok"
)

ana = getir(ana_url)

print(
    "Ana sayfa HTTP:",
    ana.status_code
)


# ============================================================
# KATEGORİ ID'LERİNİ BUL
# ============================================================

kategori_idleri = set()

# Boş kategori = genel liste
kategori_idleri.add("")

html = ana.text

# HTML içinde geçen tüm FKatID değerlerini yakala
for eslesme in re.finditer(
    r"FKatID=([^&\"'<> ]*)",
    html,
    flags=re.IGNORECASE
):
    kategori_id = eslesme.group(1).strip()

    if kategori_id:
        kategori_idleri.add(
            kategori_id
        )


# href üzerinden de tara
soup = BeautifulSoup(
    html,
    "html.parser"
)

for a in soup.find_all(
    "a",
    href=True
):
    href = a.get("href", "")

    if "FKatID" not in href:
        continue

    tam_url = urljoin(
        BASE_URL,
        href
    )

    query = parse_qs(
        urlparse(
            tam_url
        ).query
    )

    degerler = query.get(
        "FKatID",
        []
    )

    for deger in degerler:
        deger = deger.strip()

        if deger:
            kategori_idleri.add(
                deger
            )


kategori_idleri = sorted(
    kategori_idleri,
    key=lambda x: (
        x != "",
        x
    )
)

print("")
print("==============================")
print(
    "BULUNAN KATEGORİ SAYISI:",
    len(kategori_idleri)
)
print("==============================")


# ============================================================
# TÜM KATEGORİ + SAYFALARI GEZ
# ============================================================

tum_urunler = {}
kategori_sonuclari = []

for kategori_sirasi, kategori_id in enumerate(
    kategori_idleri,
    start=1
):

    gorulen_bu_kategori = set()

    onceki_sayfa_kodlari = None

    print("")
    print(
        f"[{kategori_sirasi}/{len(kategori_idleri)}] "
        f"Kategori: {kategori_id or 'GENEL'}"
    )

    for sayfa in range(
        1,
        1001
    ):
        url = (
            f"{BASE_URL}/YeniSiparisGir.asp"
            "?FView=list"
            f"&FKatID={kategori_id}"
            f"&sayfa={sayfa}"
            "&FAdi="
            "&F=Ara"
            "&Sirala=Yok"
        )

        cevap = getir(
            url
        )

        sayfa_soup = BeautifulSoup(
            cevap.text,
            "html.parser"
        )

        satirlar = sayfa_soup.select(
            "tr.urun-klavye-satiri"
        )

        if not satirlar:
            print(
                f"  Son sayfa: {sayfa - 1}"
            )
            break

        kodlar = []

        for satir in satirlar:
            kod = (
                satir.get(
                    "id",
                    ""
                )
                .strip()
            )

            if kod:
                kodlar.append(
                    kod
                )

        if not kodlar:
            print(
                f"  {sayfa}. sayfada kod okunamadı."
            )
            break

        # Site son sayfadan sonra aynı sayfayı
        # tekrar döndürüyorsa sonsuz döngüyü kes
        if (
            onceki_sayfa_kodlari is not None
            and kodlar == onceki_sayfa_kodlari
        ):
            print(
                f"  Sayfa tekrarı başladı: {sayfa}"
            )
            break

        onceki_sayfa_kodlari = kodlar

        yeni_global = 0

        for kod in kodlar:
            gorulen_bu_kategori.add(
                kod
            )

            if kod not in tum_urunler:
                tum_urunler[kod] = {
                    "kategori": kategori_id,
                    "ilk_sayfa": sayfa
                }

                yeni_global += 1

        print(
            f"  Sayfa {sayfa}: "
            f"{len(kodlar)} ürün | "
            f"global yeni {yeni_global} | "
            f"toplam farklı {len(tum_urunler)}"
        )

        time.sleep(
            0.15
        )

    kategori_sonuclari.append({
        "kategori": kategori_id or "GENEL",
        "urun_sayisi": len(
            gorulen_bu_kategori
        )
    })


# ============================================================
# SONUÇ
# ============================================================

print("")
print("====================================")
print("KATEGORİ SONUÇLARI")
print("====================================")

for sonuc in kategori_sonuclari:
    print(
        f"{sonuc['kategori']} : "
        f"{sonuc['urun_sayisi']} ürün"
    )


print("")
print("====================================")
print("KATALOG TARAMASI TAMAMLANDI")
print("====================================")
print(
    "Kategori sayısı:",
    len(kategori_idleri)
)
print(
    "TOPLAM FARKLI ÜRÜN:",
    len(tum_urunler)
)
print("====================================")
