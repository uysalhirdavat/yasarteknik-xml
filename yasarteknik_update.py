import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET

BASE_URL = "https://bayi.yasarteknik.com.tr"

XML_DOSYASI = "yasarteknik.xml"
GECICI_XML = "yasarteknik.tmp.xml"
BARKOD_MAP_DOSYASI = "barkod_map.json"

# Güvenlik sınırı
MAX_SAYFA = 500

# Barkod serimiz
BARKOD_PREFIX = "uyl12092026999"

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
# YARDIMCI FONKSİYONLAR
# ============================================================

def temiz_metin(deger):
    if deger is None:
        return ""

    return " ".join(
        str(deger)
        .replace("\xa0", " ")
        .split()
    ).strip()


def xml_metin(deger):
    return escape(
        temiz_metin(deger),
        {
            '"': "&quot;",
            "'": "&apos;"
        }
    )


def cdata_temizle(deger):
    if not deger:
        return ""

    return str(deger).replace(
        "]]>",
        "]]]]><![CDATA[>"
    )


def turk_fiyat_to_xml(deger):
    if not deger:
        return "0.00"

    fiyat = str(deger)

    fiyat = (
        fiyat
        .replace("\xa0", " ")
        .replace("TRY", "")
        .replace("TRL", "")
        .replace("TL", "")
        .replace("EUR", "")
        .replace("USD", "")
        .replace("€", "")
        .replace("$", "")
        .replace("₺", "")
        .strip()
    )

    fiyat = re.sub(
        r"[^0-9,.\-]",
        "",
        fiyat
    )

    if "," in fiyat:
        fiyat = (
            fiyat
            .replace(".", "")
            .replace(",", ".")
        )

    try:
        return f"{float(fiyat):.2f}"
    except Exception:
        return "0.00"


def para_birimi_bul(fiyat):
    upper = str(fiyat).upper()

    if "EUR" in upper or "€" in upper:
        return "EUR"

    if "USD" in upper or "$" in upper:
        return "USD"

    return "TRL"


def kdv_bul(kdv):
    eslesme = re.search(
        r"(\d+)",
        str(kdv)
    )

    if eslesme:
        return eslesme.group(1)

    return "20"


def stok_bul(satir):
    """
    YEŞİL   = 100
    TURUNCU = 0
    KIRMIZI = 0
    BİLİNMİYOR = 0
    """

    html = str(satir).lower()

    if "#1ab394" in html:
        return "STOKTA_VAR", 100

    if (
        "#f8ac59" in html
        or "orange" in html
        or "kritik stok" in html
    ):
        return "KRITIK", 0

    if (
        "#ed5565" in html
        or "red" in html
        or "stokta yok" in html
    ):
        return "STOKTA_YOK", 0

    return "BILINMIYOR", 0


# ============================================================
# BARKOD HARİTASINI OKU
# ============================================================

barkod_map = {}

if os.path.exists(BARKOD_MAP_DOSYASI):
    try:
        with open(
            BARKOD_MAP_DOSYASI,
            "r",
            encoding="utf-8"
        ) as f:
            barkod_map = json.load(f)

        print(
            "Barkod haritası okundu:",
            len(barkod_map)
        )

    except Exception as e:
        raise Exception(
            f"Barkod haritası okunamadı: {e}"
        )


# Mevcut XML'deki barkodları da haritaya ekle
if os.path.exists(XML_DOSYASI):
    try:
        agac = ET.parse(XML_DOSYASI)
        kok = agac.getroot()

        for item in kok.findall(".//item"):
            kod = temiz_metin(
                item.findtext("code")
                or item.findtext("id")
            )

            barkod = temiz_metin(
                item.findtext("barcode")
            )

            if kod and barkod and kod not in barkod_map:
                barkod_map[kod] = barkod

    except Exception as e:
        print(
            "Mevcut XML barkod okuma uyarısı:",
            e
        )


kullanilan_barkodlar = set(
    barkod_map.values()
)


def yeni_barkod_uret():
    sayac = 1

    while True:
        barkod = (
            BARKOD_PREFIX
            + f"{sayac:03d}"
        )

        if barkod not in kullanilan_barkodlar:
            kullanilan_barkodlar.add(barkod)
            return barkod

        sayac += 1


# ============================================================
# YAŞAR TEKNİK GİRİŞ
# ============================================================

ilk = session.get(
    f"{BASE_URL}/Login.asp",
    timeout=30
)

ilk.raise_for_status()

login_data = {
    "KullaniciAdi": MUSTERI_KODU,
    "KullaniciKodu": KULLANICI_KODU,
    "Sifre": SIFRE
}

login_headers = {
    "Accept": "*/*",
    "Content-Type": (
        "application/x-www-form-urlencoded; charset=UTF-8"
    ),
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/Login.asp",
    "X-Requested-With": "XMLHttpRequest"
}

login = session.post(
    f"{BASE_URL}/ajax/Login.asp",
    data=login_data,
    headers=login_headers,
    timeout=30,
    allow_redirects=False
)

if (
    login.status_code != 200
    or login.text.strip() != "1"
):
    raise Exception(
        "Yaşar Teknik girişi başarısız!"
    )

print("YAŞAR TEKNİK GİRİŞİ BAŞARILI")


# ============================================================
# OTURUM KONTROLÜ
# ============================================================

kontrol = session.get(
    f"{BASE_URL}/Default.asp",
    timeout=30,
    allow_redirects=True
)

kontrol.raise_for_status()

html = kontrol.text.lower()

if not (
    "toplam borç" in html
    or "toplam borc" in html
    or "toplam alacak" in html
    or "bekleyen sipariş" in html
    or "bekleyen siparis" in html
    or "hızlı ürün ara" in html
    or "hizli urun ara" in html
):
    raise Exception(
        "Yaşar Teknik oturumu doğrulanamadı!"
    )


# ============================================================
# TÜM SAYFALARI TARA
# ============================================================

tum_satirlar = []
gorulen_kodlar = set()
onceki_sayfa_kodlari = None

print("")
print("====================================")
print("TÜM ÜRÜN SAYFALARI TARANIYOR")
print("====================================")

for sayfa in range(1, MAX_SAYFA + 1):

    urun_url = (
        f"{BASE_URL}/YeniSiparisGir.asp"
        "?FView=list"
        "&FKatID="
        f"&sayfa={sayfa}"
        "&FAdi="
        "&F=Ara"
        "&Sirala=Yok"
    )

    cevap = session.get(
        urun_url,
        timeout=45,
        allow_redirects=True
    )

    cevap.raise_for_status()

    if "login.asp" in cevap.url.lower():
        raise Exception(
            f"{sayfa}. sayfada oturum kapandı."
        )

    soup = BeautifulSoup(
        cevap.text,
        "html.parser"
    )

    satirlar = soup.select(
        "tr.urun-klavye-satiri"
    )

    if not satirlar:
        print(
            f"{sayfa}. sayfada ürün yok. Tarama tamamlandı."
        )
        break

    sayfa_kodlari = []

    for satir in satirlar:
        kod = temiz_metin(
            satir.get("id", "")
        )

        if kod:
            sayfa_kodlari.append(kod)

    if not sayfa_kodlari:
        raise Exception(
            f"{sayfa}. sayfada ürün satırı var fakat kod okunamadı."
        )

    # Aynı sayfa tekrar dönüyorsa sonsuz döngüyü engelle
    if (
        onceki_sayfa_kodlari is not None
        and sayfa_kodlari == onceki_sayfa_kodlari
    ):
        raise Exception(
            f"{sayfa}. sayfa önceki sayfayla aynı geldi. "
            "Tarama güvenlik nedeniyle durduruldu."
        )

    onceki_sayfa_kodlari = sayfa_kodlari

    yeni_sayisi = 0

    for satir in satirlar:

        kod = temiz_metin(
            satir.get("id", "")
        )

        if not kod:
            continue

        if kod in gorulen_kodlar:
            continue

        gorulen_kodlar.add(kod)
        tum_satirlar.append(satir)
        yeni_sayisi += 1

    print(
        f"Sayfa {sayfa}: "
        f"{len(satirlar)} satır | "
        f"{yeni_sayisi} yeni ürün | "
        f"Toplam: {len(tum_satirlar)}"
    )

else:
    raise Exception(
        f"{MAX_SAYFA} sayfa sınırına ulaşıldı. "
        "Canlı XML değiştirilmedi."
    )


if len(tum_satirlar) <= 50:
    raise Exception(
        "Tüm katalog taramasında yalnızca "
        f"{len(tum_satirlar)} ürün bulundu. "
        "Beklenenden az olduğu için canlı XML değiştirilmedi."
    )


print("")
print(
    "TOPLAM BULUNAN ÜRÜN:",
    len(tum_satirlar)
)


# ============================================================
# TÜM ÜRÜNLERİN DETAYLARINI ÇEK
# ============================================================

urunler = []
hatalar = []

toplam = len(tum_satirlar)

print("")
print("====================================")
print("ÜRÜN DETAYLARI ÇEKİLİYOR")
print("====================================")

for sira, satir in enumerate(
    tum_satirlar,
    start=1
):

    try:
        urun_kodu = temiz_metin(
            satir.get("id", "")
        )

        if not urun_kodu:
            raise Exception(
                "Ürün kodu boş."
            )

        stok_durumu, xml_stok = stok_bul(
            satir
        )

        modal = session.post(
            f"{BASE_URL}/ajax/Urun_ModalGoster.asp",
            data={
                "ID": urun_kodu
            },
            headers={
                "Referer": (
                    f"{BASE_URL}/YeniSiparisGir.asp"
                ),
                "X-Requested-With": "XMLHttpRequest"
            },
            timeout=45
        )

        modal.raise_for_status()

        modal_soup = BeautifulSoup(
            modal.text,
            "html.parser"
        )

        baslik = modal_soup.find("h5")

        urun_adi = (
            temiz_metin(
                baslik.get_text(
                    " ",
                    strip=True
                )
            )
            if baslik
            else ""
        )

        if not urun_adi:
            raise Exception(
                "Ürün adı bulunamadı."
            )


        # ------------------------------------
        # DETAY TABLOSU
        # ------------------------------------

        alanlar = {}

        for detay_satiri in modal_soup.select(
            "table tr"
        ):
            th = detay_satiri.find("th")
            td = detay_satiri.find("td")

            if not th or not td:
                continue

            anahtar = temiz_metin(
                th.get_text(
                    " ",
                    strip=True
                )
            )

            deger = temiz_metin(
                td.get_text(
                    " ",
                    strip=True
                )
            )

            alanlar[anahtar] = deger


        bayi_fiyati_raw = alanlar.get(
            "Bayi Fiyatı",
            ""
        )

        if not bayi_fiyati_raw:
            raise Exception(
                "Bayi fiyatı bulunamadı."
            )

        bayi_fiyati = turk_fiyat_to_xml(
            bayi_fiyati_raw
        )

        para_birimi = para_birimi_bul(
            bayi_fiyati_raw
        )

        kdv = kdv_bul(
            alanlar.get(
                "KDV",
                "20"
            )
        )


        # ------------------------------------
        # AÇIKLAMA
        # ------------------------------------

        aciklama_alani = modal_soup.select_one(
            "#home"
        )

        if aciklama_alani:
            aciklama_html = (
                aciklama_alani
                .decode_contents()
                .strip()
            )
        else:
            aciklama_html = ""


        # ------------------------------------
        # GÖRSELLER
        # ------------------------------------

        gorseller = []

        for img in modal_soup.select(
            "#mainCarousel img"
        ):
            src = temiz_metin(
                img.get(
                    "src",
                    ""
                )
            )

            if (
                src
                and src not in gorseller
            ):
                gorseller.append(src)

        # Entegra'ya ilk 4 görsel
        gorseller = gorseller[:4]


        # ------------------------------------
        # BARKOD
        # ------------------------------------

        if urun_kodu in barkod_map:
            barkod = barkod_map[
                urun_kodu
            ]
        else:
            barkod = yeni_barkod_uret()
            barkod_map[
                urun_kodu
            ] = barkod


        # ------------------------------------
        # MARKA
        # ------------------------------------

        marka = ""

        if urun_adi:
            marka = urun_adi.split()[0]


        urunler.append({
            "id": urun_kodu,
            "code": urun_kodu,
            "label": urun_adi,
            "stock": xml_stok,
            "stok_durumu": stok_durumu,
            "details": aciklama_html,
            "currency": para_birimi,
            "price1": bayi_fiyati,
            "tax": kdv,
            "barcode": barkod,
            "brand": marka,
            "mainCategory": "Yasar Teknik",
            "category": "Genel",
            "pictures": gorseller
        })

        print(
            f"{sira}/{toplam} | "
            f"{urun_kodu} | "
            f"{stok_durumu}->{xml_stok} | "
            f"{bayi_fiyati} {para_birimi}"
        )

        # Siteyi gereksiz zorlamayalım
        time.sleep(0.12)

    except Exception as e:

        hata = (
            f"{sira}/{toplam} "
            f"{satir.get('id', '')}: {e}"
        )

        hatalar.append(hata)

        print(
            "HATA:",
            hata
        )


# ============================================================
# TÜM ÜRÜNLER EKSİKSİZ Mİ?
# ============================================================

if hatalar:

    print("")
    print("====================================")
    print("HATALI ÜRÜNLER")
    print("====================================")

    for hata in hatalar:
        print(hata)

    raise Exception(
        f"{len(hatalar)} üründe hata var. "
        "Canlı XML değiştirilmedi."
    )


if len(urunler) != len(tum_satirlar):
    raise Exception(
        "Ürün sayıları uyuşmuyor. "
        "Canlı XML değiştirilmedi."
    )


# ============================================================
# XML OLUŞTUR
# ============================================================

xml_satirlari = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    "<root>"
]

for urun in urunler:

    xml_satirlari.append(
        "  <item>"
    )

    xml_satirlari.append(
        f"    <id>{xml_metin(urun['id'])}</id>"
    )

    xml_satirlari.append(
        f"    <code>{xml_metin(urun['code'])}</code>"
    )

    xml_satirlari.append(
        f"    <label>{xml_metin(urun['label'])}</label>"
    )

    xml_satirlari.append(
        f"    <stock>{urun['stock']}</stock>"
    )

    xml_satirlari.append(
        "    <details><![CDATA["
        + cdata_temizle(
            urun["details"]
        )
        + "]]></details>"
    )

    xml_satirlari.append(
        f"    <currency>{xml_metin(urun['currency'])}</currency>"
    )

    xml_satirlari.append(
        f"    <price1>{urun['price1']}</price1>"
    )

    xml_satirlari.append(
        f"    <tax>{urun['tax']}</tax>"
    )

    xml_satirlari.append(
        f"    <barcode>{xml_metin(urun['barcode'])}</barcode>"
    )

    xml_satirlari.append(
        f"    <brand>{xml_metin(urun['brand'])}</brand>"
    )

    xml_satirlari.append(
        f"    <mainCategory>{xml_metin(urun['mainCategory'])}</mainCategory>"
    )

    xml_satirlari.append(
        f"    <category>{xml_metin(urun['category'])}</category>"
    )

    for no, resim in enumerate(
        urun["pictures"],
        start=1
    ):
        xml_satirlari.append(
            f"    <picture{no}>"
            f"{xml_metin(resim)}"
            f"</picture{no}>"
        )

    xml_satirlari.append(
        "  </item>"
    )


xml_satirlari.append(
    "</root>"
)

xml_icerigi = "\n".join(
    xml_satirlari
)


# ============================================================
# ÖNCE GEÇİCİ XML
# ============================================================

with open(
    GECICI_XML,
    "w",
    encoding="utf-8"
) as f:

    f.write(
        xml_icerigi
    )


# ============================================================
# XML GEÇERLİ Mİ?
# ============================================================

try:
    test_agac = ET.parse(
        GECICI_XML
    )

    test_root = test_agac.getroot()

    xml_urun_sayisi = len(
        test_root.findall(
            ".//item"
        )
    )

except Exception as e:
    raise Exception(
        f"Yeni XML geçersiz: {e}. "
        "Canlı XML değiştirilmedi."
    )


if xml_urun_sayisi != len(urunler):
    raise Exception(
        "Geçici XML ürün sayısı uyuşmuyor. "
        "Canlı XML değiştirilmedi."
    )


# ============================================================
# BARKOD HARİTASINI KAYDET
# ============================================================

with open(
    BARKOD_MAP_DOSYASI,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        barkod_map,
        f,
        ensure_ascii=False,
        indent=2,
        sort_keys=True
    )


# ============================================================
# TÜM İŞLEMLER BAŞARILIYSA CANLI XML'E GEÇ
# ============================================================

os.replace(
    GECICI_XML,
    XML_DOSYASI
)


# ============================================================
# SONUÇ
# ============================================================

stokta_var = sum(
    1
    for urun in urunler
    if urun["stock"] == 100
)

kapali = sum(
    1
    for urun in urunler
    if urun["stock"] == 0
)

print("")
print("====================================")
print("YAŞAR TEKNİK TÜM XML TAMAMLANDI")
print("====================================")
print("Toplam ürün:", len(urunler))
print("Stok açık (100):", stokta_var)
print("Stok kapalı (0):", kapali)
print("Barkod sayısı:", len(barkod_map))
print("XML:", XML_DOSYASI)
print("====================================")
