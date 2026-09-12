import os
import re
import requests
from bs4 import BeautifulSoup
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET

BASE_URL = "https://bayi.yasarteknik.com.tr"
XML_DOSYASI = "yasarteknik.xml"
GECICI_XML = "yasarteknik.tmp.xml"

# İlk 50 ürün testi
HEDEF_URUN_SAYISI = 50

# Bizim barkod başlangıcımız
BARKOD_PREFIX = "uyl12092026999"
BARKOD_BASLANGIC = 1

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
    """
    1.409,09 TL -> 1409.09
    775,00 TL   -> 775.00
    25,50 EUR   -> 25.50
    """

    if not deger:
        return "0.00"

    fiyat = str(deger)

    fiyat = (
        fiyat
        .replace("\xa0", " ")
        .replace("TL", "")
        .replace("TRY", "")
        .replace("TRL", "")
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

    # Türk formatı:
    # 1.409,09
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
    Yaşar Teknik kuralı:

    YEŞİL   -> 100
    TURUNCU -> 0
    KIRMIZI -> 0
    BİLİNMİYOR -> 0
    """

    satir_html = str(satir).lower()

    if "#1ab394" in satir_html:
        return "STOKTA_VAR", 100

    if (
        "#f8ac59" in satir_html
        or "orange" in satir_html
        or "kritik stok" in satir_html
    ):
        return "KRITIK", 0

    if (
        "#ed5565" in satir_html
        or "red" in satir_html
        or "stokta yok" in satir_html
    ):
        return "STOKTA_YOK", 0

    return "BILINMIYOR", 0


# ============================================================
# ESKİ BARKODLARI OKU
# ============================================================

eski_barkodlar = {}

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

            if kod and barkod:
                eski_barkodlar[kod] = barkod

        print(
            "Korunacak eski barkod sayısı:",
            len(eski_barkodlar)
        )

    except Exception as e:
        print(
            "Eski XML barkodları okunamadı:",
            str(e)
        )


kullanilan_barkodlar = set(
    eski_barkodlar.values()
)


def yeni_barkod_uret():
    sayac = BARKOD_BASLANGIC

    while True:
        barkod = (
            BARKOD_PREFIX
            + f"{sayac:03d}"
        )

        if barkod not in kullanilan_barkodlar:
            kullanilan_barkodlar.add(
                barkod
            )
            return barkod

        sayac += 1


# ============================================================
# GİRİŞ
# ============================================================

ilk = session.get(
    f"{BASE_URL}/Login.asp",
    timeout=30
)

ilk.raise_for_status()

print(
    "Login sayfası HTTP:",
    ilk.status_code
)

login_data = {
    "KullaniciAdi": MUSTERI_KODU,
    "KullaniciKodu": KULLANICI_KODU,
    "Sifre": SIFRE
}

login_headers = {
    "Accept": "*/*",
    "Content-Type": (
        "application/x-www-form-urlencoded; "
        "charset=UTF-8"
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

print(
    "YAŞAR TEKNİK GİRİŞİ BAŞARILI"
)


# ============================================================
# OTURUM KONTROLÜ
# ============================================================

kontrol = session.get(
    f"{BASE_URL}/Default.asp",
    timeout=30,
    allow_redirects=True
)

kontrol.raise_for_status()

kontrol_html = kontrol.text.lower()

if not (
    "toplam borç" in kontrol_html
    or "toplam borc" in kontrol_html
    or "toplam alacak" in kontrol_html
    or "bekleyen sipariş" in kontrol_html
    or "bekleyen siparis" in kontrol_html
    or "hızlı ürün ara" in kontrol_html
    or "hizli urun ara" in kontrol_html
):
    raise Exception(
        "Yaşar Teknik oturumu doğrulanamadı!"
    )


# ============================================================
# İLK SAYFADAKİ 50 ÜRÜN
# ============================================================

urun_url = (
    f"{BASE_URL}/YeniSiparisGir.asp"
    "?FView=list"
    "&FKatID="
    "&sayfa=1"
    "&FAdi="
    "&F=Ara"
    "&Sirala=Yok"
)

urun_sayfasi = session.get(
    urun_url,
    timeout=30,
    allow_redirects=True
)

urun_sayfasi.raise_for_status()

soup = BeautifulSoup(
    urun_sayfasi.text,
    "html.parser"
)

urun_satirlari = soup.select(
    "tr.urun-klavye-satiri"
)

print(
    "Sayfadaki ürün sayısı:",
    len(urun_satirlari)
)

if len(urun_satirlari) < HEDEF_URUN_SAYISI:
    raise Exception(
        f"Beklenen en az {HEDEF_URUN_SAYISI} ürün, "
        f"ama yalnızca {len(urun_satirlari)} ürün geldi. "
        "Canlı XML değiştirilmedi."
    )

urun_satirlari = urun_satirlari[
    :HEDEF_URUN_SAYISI
]


# ============================================================
# ÜRÜNLERİ ÇEK
# ============================================================

urunler = []

for sira, satir in enumerate(
    urun_satirlari,
    start=1
):

    urun_kodu = temiz_metin(
        satir.get("id", "")
    )

    if not urun_kodu:
        raise Exception(
            f"{sira}. ürünün kodu bulunamadı."
        )

    stok_durumu, xml_stok = stok_bul(
        satir
    )

    # ----------------------------------------
    # DETAY MODALI
    # ----------------------------------------

    modal = session.post(
        f"{BASE_URL}/ajax/Urun_ModalGoster.asp",
        data={
            "ID": urun_kodu
        },
        headers={
            "Referer": urun_sayfasi.url,
            "X-Requested-With": "XMLHttpRequest"
        },
        timeout=30
    )

    modal.raise_for_status()

    modal_soup = BeautifulSoup(
        modal.text,
        "html.parser"
    )

    # ----------------------------------------
    # ÜRÜN ADI
    # ----------------------------------------

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
            f"{urun_kodu} ürün adı bulunamadı."
        )

    # ----------------------------------------
    # DETAY TABLOSU
    # ----------------------------------------

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

    # ----------------------------------------
    # AÇIKLAMA
    # ----------------------------------------

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

    # ----------------------------------------
    # GÖRSELLER
    # ----------------------------------------

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
            gorseller.append(
                src
            )

    # Entegra için ilk 4 görsel
    gorseller = gorseller[:4]

    # ----------------------------------------
    # BARKOD
    # ----------------------------------------

    if urun_kodu in eski_barkodlar:
        barkod = eski_barkodlar[
            urun_kodu
        ]
    else:
        barkod = yeni_barkod_uret()

    # ----------------------------------------
    # MARKA
    # ----------------------------------------

    # Ürün adının ilk kelimesini marka olarak
    # kullanıyoruz. Test XML'i için.
    marka = ""

    if urun_adi:
        marka = urun_adi.split()[0]

    # ----------------------------------------
    # XML ÜRÜN VERİSİ
    # ----------------------------------------

    urun = {
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
    }

    urunler.append(
        urun
    )

    print(
        f"{sira}/{HEDEF_URUN_SAYISI} | "
        f"{urun_kodu} | "
        f"{urun_adi} | "
        f"{stok_durumu} -> {xml_stok} | "
        f"{bayi_fiyati} {para_birimi} | "
        f"{barkod}"
    )


# ============================================================
# GÜVENLİK KONTROLÜ
# ============================================================

if len(urunler) != HEDEF_URUN_SAYISI:
    raise Exception(
        f"XML için {HEDEF_URUN_SAYISI} ürün bekleniyordu, "
        f"{len(urunler)} ürün hazırlandı. "
        "Canlı XML değiştirilmedi."
    )


# ============================================================
# XML OLUŞTUR
# ============================================================

xml_satirlari = []

xml_satirlari.append(
    '<?xml version="1.0" encoding="UTF-8"?>'
)

xml_satirlari.append(
    "<root>"
)

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
# ÖNCE GEÇİCİ DOSYAYA YAZ
# ============================================================

with open(
    GECICI_XML,
    "w",
    encoding="utf-8"
) as dosya:

    dosya.write(
        xml_icerigi
    )


# ============================================================
# OLUŞAN XML'İ TEKRAR KONTROL ET
# ============================================================

try:
    test_agac = ET.parse(
        GECICI_XML
    )

    test_root = test_agac.getroot()

    item_sayisi = len(
        test_root.findall(
            ".//item"
        )
    )

except Exception as e:
    raise Exception(
        "Yeni XML geçersiz. "
        f"Canlı XML değiştirilmedi: {e}"
    )


if item_sayisi != HEDEF_URUN_SAYISI:
    raise Exception(
        f"Geçici XML içinde {item_sayisi} ürün var. "
        f"{HEDEF_URUN_SAYISI} bekleniyordu. "
        "Canlı XML değiştirilmedi."
    )


# ============================================================
# TÜM TESTLER BAŞARILIYSA CANLI XML'E GEÇİR
# ============================================================

os.replace(
    GECICI_XML,
    XML_DOSYASI
)

print("")
print("====================================")
print("YAŞAR TEKNİK XML BAŞARIYLA OLUŞTU")
print("Ürün sayısı:", len(urunler))
print("Dosya:", XML_DOSYASI)
print("====================================")
