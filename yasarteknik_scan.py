import os
import re
import time
import requests

from bs4 import BeautifulSoup
from urllib.parse import (
    urljoin,
    urlparse,
    parse_qs,
    urlencode,
    urlunparse
)

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


# ============================================================
# GÜVENLİK
# ============================================================

# Bu sayfalara tarama sırasında kesinlikle GET atma
YASAK_KELIMELER = (
    "logout",
    "cikis",
    "sepeteekle",
    "sepetten",
    "siparisver",
    "siparistamamla",
    "sil.asp",
    "delete",
    "modal_sepeteekle",
    "siparisgir_sepet",
    "/ajax/"
)

# Sadece portal içindeki sayfaları gezeceğiz
HOST = urlparse(BASE_URL).netloc.lower()


# ============================================================
# YARDIMCI
# ============================================================

def temiz(deger):
    if deger is None:
        return ""

    return " ".join(
        str(deger)
        .replace("\xa0", " ")
        .split()
    ).strip()


def guvenli_url_mi(url):
    try:
        parsed = urlparse(url)

        if parsed.netloc and parsed.netloc.lower() != HOST:
            return False

        lower = url.lower()

        if any(kelime in lower for kelime in YASAK_KELIMELER):
            return False

        return True

    except Exception:
        return False


def normalize_url(url):
    parsed = urlparse(url)

    # Fragment kaldır
    parsed = parsed._replace(fragment="")

    return urlunparse(parsed)


# ============================================================
# GİRİŞ
# ============================================================

def giris_yap():
    session.cookies.clear()

    ilk = session.get(
        f"{BASE_URL}/Login.asp",
        timeout=30
    )

    ilk.raise_for_status()

    login = session.post(
        f"{BASE_URL}/ajax/Login.asp",
        data={
            "KullaniciAdi": MUSTERI_KODU,
            "KullaniciKodu": KULLANICI_KODU,
            "Sifre": SIFRE
        },
        headers={
            "Accept": "*/*",
            "Content-Type":
                "application/x-www-form-urlencoded; charset=UTF-8",
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

    for no in range(1, deneme + 1):

        try:
            cevap = session.get(
                url,
                timeout=45,
                allow_redirects=True
            )

            if "login.asp" in cevap.url.lower():
                print(
                    "Oturum düştü. Yeniden giriş yapılıyor..."
                )

                giris_yap()
                time.sleep(1)
                continue

            cevap.raise_for_status()

            return cevap

        except Exception as e:

            son_hata = e

            print(
                f"İstek hatası {no}/{deneme}: {e}"
            )

            if no < deneme:

                try:
                    giris_yap()
                except Exception:
                    pass

                time.sleep(no * 2)

    raise son_hata


# ============================================================
# HTML'DEN ÜRÜN KODU BUL
# ============================================================

def urun_kodlarini_bul(html):
    bulunan = set()

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # 1. Bizim bildiğimiz ürün satırları
    for satir in soup.select(
        "tr.urun-klavye-satiri[id]"
    ):
        kod = temiz(
            satir.get("id", "")
        )

        if kod:
            bulunan.add(kod)

    # 2. Ürün modal çağrılarından yakala
    desenler = [
        r"""UrunModalGoster\(\s*['"]([^'"]+)['"]""",
        r"""UrunModalGost(?:er|eri)\(\s*['"]([^'"]+)['"]""",
        r"""data-item-code\s*=\s*['"]([^'"]+)['"]""",
        r"""data-product-code\s*=\s*['"]([^'"]+)['"]"""
    ]

    for desen in desenler:
        for eslesme in re.finditer(
            desen,
            html,
            flags=re.IGNORECASE
        ):
            kod = temiz(
                eslesme.group(1)
            )

            if kod:
                bulunan.add(kod)

    return bulunan


# ============================================================
# HTML'DEKİ PORTAL SAYFALARINI BUL
# ============================================================

def linkleri_bul(html, kaynak_url):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    linkler = set()

    for a in soup.find_all(
        "a",
        href=True
    ):
        href = temiz(
            a.get("href", "")
        )

        if not href:
            continue

        if href.startswith(
            (
                "#",
                "javascript:",
                "mailto:",
                "tel:"
            )
        ):
            continue

        tam = urljoin(
            kaynak_url,
            href
        )

        tam = normalize_url(tam)

        if not guvenli_url_mi(tam):
            continue

        parsed = urlparse(tam)

        # Sadece ASP sayfaları
        if not parsed.path.lower().endswith(".asp"):
            continue

        linkler.add(tam)

    return linkler


# ============================================================
# PAGINATION TARAMASI
# ============================================================

def sayfalari_tara(
    baslangic_url,
    global_urunler,
    etiket
):
    parsed = urlparse(
        baslangic_url
    )

    query = parse_qs(
        parsed.query,
        keep_blank_values=True
    )

    # sayfa parametresi yoksa yine 1'den deniyoruz
    ilk_sayfa = 1

    bu_kaynak = set()
    onceki_kodlar = None

    for sayfa in range(
        ilk_sayfa,
        1001
    ):

        yeni_query = {
            k: v[-1]
            for k, v in query.items()
        }

        yeni_query["sayfa"] = str(
            sayfa
        )

        yeni_url = urlunparse(
            parsed._replace(
                query=urlencode(
                    yeni_query
                )
            )
        )

        cevap = getir(
            yeni_url
        )

        kodlar = urun_kodlarini_bul(
            cevap.text
        )

        if not kodlar:

            if sayfa == 1:
                return {
                    "etiket": etiket,
                    "urun": 0,
                    "son_sayfa": 0
                }

            print(
                f"  {etiket} son sayfa: {sayfa - 1}"
            )
            break

        sirali = tuple(
            sorted(kodlar)
        )

        if (
            onceki_kodlar is not None
            and sirali == onceki_kodlar
        ):
            print(
                f"  {etiket}: sayfa tekrarı "
                f"{sayfa}. sayfada başladı."
            )
            break

        onceki_kodlar = sirali

        yeni = 0

        for kod in kodlar:

            bu_kaynak.add(kod)

            if kod not in global_urunler:
                global_urunler.add(
                    kod
                )

                yeni += 1

        print(
            f"  {etiket} | "
            f"Sayfa {sayfa}: "
            f"{len(kodlar)} ürün | "
            f"global yeni {yeni} | "
            f"toplam farklı {len(global_urunler)}"
        )

        time.sleep(
            0.12
        )

    return {
        "etiket": etiket,
        "urun": len(bu_kaynak),
        "son_sayfa": sayfa - 1
    }


# ============================================================
# BAŞLA
# ============================================================

giris_yap()


# ============================================================
# 1 - GENEL ÜRÜN LİSTESİ
# ============================================================

tum_urunler = set()
kaynak_sonuclari = []

genel_url = (
    f"{BASE_URL}/YeniSiparisGir.asp"
    "?FView=list"
    "&FKatID="
    "&sayfa=1"
    "&FAdi="
    "&F=Ara"
    "&Sirala=Yok"
)

print("")
print("====================================")
print("1 - GENEL LİSTE TARANIYOR")
print("====================================")

genel_sonuc = sayfalari_tara(
    genel_url,
    tum_urunler,
    "GENEL"
)

kaynak_sonuclari.append(
    genel_sonuc
)

genel_urunler = set(
    tum_urunler
)

print("")
print(
    "GENEL TOPLAM FARKLI ÜRÜN:",
    len(genel_urunler)
)


# ============================================================
# 2 - PORTAL SAYFALARINI KEŞFET
# ============================================================

print("")
print("====================================")
print("2 - PORTAL SAYFALARI KEŞFEDİLİYOR")
print("====================================")

baslangiclar = [
    f"{BASE_URL}/Default.asp",
    genel_url,
    f"{BASE_URL}/sinirlistok.asp",
    f"{BASE_URL}/FiyatListesi.asp"
]

ziyaret_edildi = set()
bekleyen = []

for url in baslangiclar:
    if guvenli_url_mi(url):
        bekleyen.append(
            normalize_url(url)
        )


# Sadece keşif için makul sınır
MAX_PORTAL_SAYFASI = 150

kesfedilen_sayfalar = set()

while (
    bekleyen
    and len(ziyaret_edildi) < MAX_PORTAL_SAYFASI
):

    url = bekleyen.pop(0)

    if url in ziyaret_edildi:
        continue

    ziyaret_edildi.add(url)

    try:
        cevap = getir(
            url
        )

    except Exception as e:
        print(
            "Sayfa açılamadı:",
            url,
            e
        )
        continue

    print(
        f"Keşif "
        f"{len(ziyaret_edildi)}/"
        f"{MAX_PORTAL_SAYFASI}: "
        f"{cevap.url}"
    )

    kesfedilen_sayfalar.add(
        normalize_url(
            cevap.url
        )
    )

    for link in linkleri_bul(
        cevap.text,
        cevap.url
    ):

        if (
            link not in ziyaret_edildi
            and link not in bekleyen
        ):
            bekleyen.append(
                link
            )

    time.sleep(
        0.08
    )


print("")
print(
    "Keşfedilen güvenli ASP sayfası:",
    len(kesfedilen_sayfalar)
)


# ============================================================
# 3 - KEŞFEDİLEN SAYFALARDA ÜRÜN ARA
# ============================================================

print("")
print("====================================")
print("3 - DİĞER SAYFALARDA ÜRÜN ARANIYOR")
print("====================================")

diger_kaynaklar = []

for sira, url in enumerate(
    sorted(kesfedilen_sayfalar),
    start=1
):

    # Genel sayfayı tekrar tarama
    if "yenisiparisgir.asp" in url.lower():
        continue

    try:
        cevap = getir(
            url
        )

    except Exception as e:
        print(
            f"{sira}. sayfa hata:",
            e
        )
        continue

    kodlar = urun_kodlarini_bul(
        cevap.text
    )

    if not kodlar:
        continue

    yeni = kodlar - tum_urunler

    tum_urunler.update(
        kodlar
    )

    print("")
    print(
        f"ÜRÜN BULUNAN SAYFA:"
    )
    print(
        url
    )
    print(
        "Bu sayfada ürün:",
        len(kodlar)
    )
    print(
        "GENEL dışında yeni:",
        len(yeni)
    )
    print(
        "Toplam farklı:",
        len(tum_urunler)
    )

    diger_kaynaklar.append({
        "url": url,
        "urun": len(kodlar),
        "yeni": len(yeni)
    })


# ============================================================
# 4 - ÖZEL BİLDİĞİMİZ SAYFALARDA PAGINATION
# ============================================================

print("")
print("====================================")
print("4 - ÖZEL LİSTELER SAYFALANIYOR")
print("====================================")

ozel_listeler = [
    (
        f"{BASE_URL}/sinirlistok.asp",
        "SINIRLI_STOK"
    ),
    (
        f"{BASE_URL}/FiyatListesi.asp",
        "FIYAT_LISTESI"
    )
]

for url, etiket in ozel_listeler:

    try:
        sonuc = sayfalari_tara(
            url,
            tum_urunler,
            etiket
        )

        kaynak_sonuclari.append(
            sonuc
        )

    except Exception as e:
        print(
            f"{etiket} tarama hatası:",
            e
        )


# ============================================================
# SONUÇ
# ============================================================

genel_disi = (
    tum_urunler
    - genel_urunler
)

print("")
print("====================================")
print("GENİŞ KATALOG TARAMASI TAMAMLANDI")
print("====================================")

print(
    "GENEL ÜRÜN:",
    len(genel_urunler)
)

print(
    "GENEL DIŞINDA YENİ ÜRÜN:",
    len(genel_disi)
)

print(
    "TOPLAM BENZERSİZ ÜRÜN:",
    len(tum_urunler)
)

print("")
print("ÜRÜN BULUNAN DİĞER KAYNAKLAR:")

for kaynak in diger_kaynaklar:
    print(
        kaynak["url"],
        "| ürün:",
        kaynak["urun"],
        "| yeni:",
        kaynak["yeni"]
    )

print("")
print("====================================")
