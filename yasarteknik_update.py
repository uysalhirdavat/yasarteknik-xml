import os
import re
import json
import time
import requests

from bs4 import BeautifulSoup
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET


# ============================================================
# AYARLAR
# ============================================================

BASE_URL = "https://bayi.yasarteknik.com.tr"

XML_DOSYASI = "yasarteknik.xml"
GECICI_XML = "yasarteknik.tmp.xml"
BARKOD_MAP_DOSYASI = "barkod_map.json"

BARKOD_PREFIX = "uyl12092026999"

# 12.09.2026 geniş taramada 8.283 ürün bulundu.
# Eksik taramada canlı XML'i bozmasın.
MIN_BEKLENEN_URUN = 8000

# Sayfalama güvenlik sınırı
MAX_SAYFA = 300

# HTTP deneme sayıları
GET_DENEME = 6
MODAL_DENEME = 6
STOK_DENEME = 5

# Sunucuyu gereksiz zorlamamak için küçük beklemeler
LISTE_BEKLEME = 0.10
URUN_BEKLEME = 0.08

# Uzun taramada oturumun düşmesini azaltmak için
# belirli aralıklarla yeniden giriş.
YENIDEN_GIRIS_ARALIGI = 400


# ============================================================
# GITHUB SECRETS
# ============================================================

MUSTERI_KODU = os.environ.get("YASAR_KULLANICI_ADI")
KULLANICI_KODU = os.environ.get("YASAR_KULLANICI_KODU")
SIFRE = os.environ.get("YASAR_SIFRE")

if not MUSTERI_KODU or not KULLANICI_KODU or not SIFRE:
    raise Exception("GitHub Secrets eksik!")


# ============================================================
# SESSION
# ============================================================

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


def stok_bul_html(html):
    """
    Kuralımız:

    YEŞİL   -> 100
    TURUNCU -> 0
    KIRMIZI -> 0
    Bilinmiyor -> None

    None dönerse ürün koduyla ayrıca stok araması yapacağız.
    """

    html = str(html).lower()

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

    return "BILINMIYOR", None


# ============================================================
# GİRİŞ
# ============================================================

def giris_yap():
    """
    Yaşar Teknik'e yeni oturum açar.
    Uzun taramalarda tekrar tekrar kullanılabilir.
    """

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

    if login.status_code != 200:
        raise Exception(
            f"Giriş HTTP hatası: {login.status_code}"
        )

    if login.text.strip() != "1":
        raise Exception(
            "Yaşar Teknik giriş cevabı başarısız!"
        )

    print("YAŞAR TEKNİK GİRİŞİ BAŞARILI")


# ============================================================
# GET - RETRY
# ============================================================

def guvenli_get(url, deneme=GET_DENEME):
    son_hata = None

    for no in range(1, deneme + 1):

        try:
            cevap = session.get(
                url,
                timeout=45,
                allow_redirects=True
            )

            son_url = cevap.url.lower()

            if (
                "login.asp" in son_url
                or "logout.asp" in son_url
            ):
                print(
                    f"GET oturum düştü ({no}/{deneme}). "
                    "Yeniden giriş..."
                )

                giris_yap()

                time.sleep(
                    min(no * 2, 8)
                )

                continue

            cevap.raise_for_status()

            return cevap

        except Exception as e:
            son_hata = e

            print(
                f"GET hata {no}/{deneme}: {e}"
            )

            if no < deneme:

                try:
                    giris_yap()
                except Exception as login_hatasi:
                    print(
                        "Yeniden giriş uyarısı:",
                        login_hatasi
                    )

                time.sleep(
                    min(no * 2, 10)
                )

    raise son_hata


# ============================================================
# MODAL - RETRY
# ============================================================

def guvenli_modal(urun_kodu, deneme=MODAL_DENEME):
    """
    Ürün detay modalını alır.

    Bağlantı koparsa veya logout/login'e yönlenirse
    yeniden giriş yapıp aynı ürünü tekrar dener.
    """

    son_hata = None

    for no in range(1, deneme + 1):

        try:
            cevap = session.post(
                f"{BASE_URL}/ajax/Urun_ModalGoster.asp",
                data={
                    "ID": urun_kodu
                },
                headers={
                    "Referer":
                        f"{BASE_URL}/YeniSiparisGir.asp",
                    "X-Requested-With": "XMLHttpRequest"
                },
                timeout=45,
                allow_redirects=True
            )

            son_url = cevap.url.lower()

            if (
                "logout.asp" in son_url
                or "login.asp" in son_url
            ):
                print(
                    f"{urun_kodu}: modal oturumu düştü "
                    f"({no}/{deneme})."
                )

                giris_yap()

                time.sleep(
                    min(no * 2, 8)
                )

                continue

            cevap.raise_for_status()

            # Bazen HTTP 200 olsa bile Login HTML'i gelebilir.
            kontrol = cevap.text.lower()

            if (
                "<title>oturum aç" in kontrol
                or 'name="kullaniciadi"' in kontrol
                or "/login.asp" in kontrol[:2000]
            ):
                print(
                    f"{urun_kodu}: Login HTML geldi "
                    f"({no}/{deneme})."
                )

                giris_yap()

                time.sleep(
                    min(no * 2, 8)
                )

                continue

            modal_soup = BeautifulSoup(
                cevap.text,
                "html.parser"
            )

            # Gerçek ürün modalı olduğuna dair kontrol
            if not (
                modal_soup.find("h5")
                or modal_soup.select_one("#mainCarousel")
                or modal_soup.select_one("table")
            ):
                raise Exception(
                    "Ürün modal içeriği doğrulanamadı."
                )

            return cevap

        except Exception as e:
            son_hata = e

            print(
                f"{urun_kodu}: modal hata "
                f"{no}/{deneme}: {e}"
            )

            if no < deneme:

                try:
                    giris_yap()
                except Exception as login_hatasi:
                    print(
                        "Yeniden giriş uyarısı:",
                        login_hatasi
                    )

                # RemoteDisconnected gibi durumlarda
                # biraz daha uzun beklesin.
                time.sleep(
                    min(no * 3, 15)
                )

    raise Exception(
        f"{urun_kodu} detay modalı "
        f"{deneme} denemede alınamadı: {son_hata}"
    )


# ============================================================
# ÜRÜN KODLARINI SAYFADAN BUL
# ============================================================

def sayfadaki_kodlari_bul(html):
    """
    Hem YeniSiparisGir hem FiyatListesi için
    ürün kodlarını mümkün olduğunca sağlam toplar.
    """

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    kodlar = []
    satir_map = {}

    # Öncelikle gerçek ürün satırları
    for satir in soup.select(
        "tr.urun-klavye-satiri[id]"
    ):
        kod = temiz_metin(
            satir.get("id", "")
        )

        if (
            kod
            and kod not in satir_map
        ):
            kodlar.append(kod)
            satir_map[kod] = str(satir)

    # Fiyat listesi gibi sayfalarda kodlar JS modal çağrısında da bulunabilir.
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
            kod = temiz_metin(
                eslesme.group(1)
            )

            if (
                kod
                and kod not in kodlar
            ):
                kodlar.append(kod)

    return kodlar, satir_map


# ============================================================
# BARKOD HARİTASI
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
            "Barkod haritası:",
            len(barkod_map)
        )

    except Exception as e:
        raise Exception(
            f"Barkod haritası okunamadı: {e}"
        )


# Mevcut XML'deki barkodları da koru
if os.path.exists(XML_DOSYASI):

    try:
        agac = ET.parse(
            XML_DOSYASI
        )

        kok = agac.getroot()

        for item in kok.findall(".//item"):

            kod = temiz_metin(
                item.findtext("code")
                or item.findtext("id")
            )

            barkod = temiz_metin(
                item.findtext("barcode")
            )

            if (
                kod
                and barkod
                and kod not in barkod_map
            ):
                barkod_map[kod] = barkod

    except Exception as e:
        print(
            "Eski XML barkod okuma uyarısı:",
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

            kullanilan_barkodlar.add(
                barkod
            )

            return barkod

        sayac += 1


# ============================================================
# BAŞLANGIÇ GİRİŞ
# ============================================================

giris_yap()


# ============================================================
# OTURUM KONTROL
# ============================================================

kontrol = guvenli_get(
    f"{BASE_URL}/Default.asp"
)

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
# ÜRÜN KEŞFİ
# ============================================================

urun_kayitlari = {}
genel_urunler = set()
fiyat_listesi_urunler = set()


def urun_ekle(
    kod,
    kaynak,
    satir_html=""
):
    if not kod:
        return False

    yeni = kod not in urun_kayitlari

    if yeni:
        urun_kayitlari[kod] = {
            "kod": kod,
            "kaynaklar": [],
            "stok_html": ""
        }

    if kaynak not in urun_kayitlari[kod]["kaynaklar"]:
        urun_kayitlari[kod]["kaynaklar"].append(
            kaynak
        )

    # Stok HTML'i varsa kaybetme
    if (
        satir_html
        and not urun_kayitlari[kod]["stok_html"]
    ):
        urun_kayitlari[kod]["stok_html"] = satir_html

    return yeni


# ============================================================
# 1 - YENİ SİPARİŞ GENEL LİSTESİ
# ============================================================

print("")
print("====================================")
print("1 - GENEL ÜRÜN LİSTESİ")
print("====================================")

onceki = None

for sayfa in range(
    1,
    MAX_SAYFA + 1
):

    url = (
        f"{BASE_URL}/YeniSiparisGir.asp"
        "?FView=list"
        "&FKatID="
        f"&sayfa={sayfa}"
        "&FAdi="
        "&F=Ara"
        "&Sirala=Yok"
    )

    cevap = guvenli_get(
        url
    )

    kodlar, satir_map = sayfadaki_kodlari_bul(
        cevap.text
    )

    if not kodlar:

        print(
            f"GENEL son sayfa: {sayfa - 1}"
        )

        break

    imza = tuple(kodlar)

    if (
        onceki is not None
        and imza == onceki
    ):
        print(
            f"GENEL sayfa tekrarı: {sayfa}"
        )
        break

    onceki = imza

    yeni = 0

    for kod in kodlar:

        genel_urunler.add(
            kod
        )

        if urun_ekle(
            kod,
            "GENEL",
            satir_map.get(
                kod,
                ""
            )
        ):
            yeni += 1

    print(
        f"GENEL Sayfa {sayfa}: "
        f"{len(kodlar)} ürün | "
        f"yeni {yeni} | "
        f"toplam {len(urun_kayitlari)}"
    )

    time.sleep(
        LISTE_BEKLEME
    )

else:
    raise Exception(
        "GENEL sayfa güvenlik sınırına ulaştı."
    )


# ============================================================
# 2 - FİYAT LİSTESİ
# ============================================================

print("")
print("====================================")
print("2 - FİYAT LİSTESİ")
print("====================================")

onceki = None

for sayfa in range(
    1,
    MAX_SAYFA + 1
):

    url = (
        f"{BASE_URL}/FiyatListesi.asp"
        f"?sayfa={sayfa}"
        "&F="
        "&FAdi="
        "&FHizliFirsat="
        "&FHizliInsert="
        "&Sirala="
    )

    cevap = guvenli_get(
        url
    )

    kodlar, satir_map = sayfadaki_kodlari_bul(
        cevap.text
    )

    if not kodlar:

        print(
            f"FIYAT_LISTESI son sayfa: {sayfa - 1}"
        )

        break

    imza = tuple(kodlar)

    if (
        onceki is not None
        and imza == onceki
    ):
        print(
            f"FIYAT_LISTESI sayfa tekrarı: {sayfa}"
        )
        break

    onceki = imza

    yeni = 0

    for kod in kodlar:

        fiyat_listesi_urunler.add(
            kod
        )

        if urun_ekle(
            kod,
            "FIYAT_LISTESI",
            satir_map.get(
                kod,
                ""
            )
        ):
            yeni += 1

    print(
        f"FIYAT_LISTESI Sayfa {sayfa}: "
        f"{len(kodlar)} ürün | "
        f"yeni {yeni} | "
        f"toplam {len(urun_kayitlari)}"
    )

    time.sleep(
        LISTE_BEKLEME
    )

else:
    raise Exception(
        "FiyatListesi sayfa güvenlik sınırına ulaştı."
    )


# ============================================================
# KEŞİF GÜVENLİK KONTROLÜ
# ============================================================

toplam_kesif = len(
    urun_kayitlari
)

print("")
print("====================================")
print("ÜRÜN KEŞFİ TAMAMLANDI")
print("====================================")
print(
    "GENEL:",
    len(genel_urunler)
)
print(
    "FIYAT LISTESI:",
    len(fiyat_listesi_urunler)
)
print(
    "TOPLAM BENZERSİZ:",
    toplam_kesif
)
print("====================================")


if toplam_kesif < MIN_BEKLENEN_URUN:

    raise Exception(
        f"Yalnızca {toplam_kesif} ürün bulundu. "
        f"Minimum {MIN_BEKLENEN_URUN} bekleniyordu. "
        "Canlı XML değiştirilmedi."
    )


# ============================================================
# STOK FALLBACK
# ============================================================

def stok_ara(urun_kodu):
    """
    FiyatListesi'nden gelen üründe stok rengi yoksa
    ürün koduyla YeniSiparisGir.asp içinde arar.
    """

    for no in range(
        1,
        STOK_DENEME + 1
    ):

        try:
            url = (
                f"{BASE_URL}/YeniSiparisGir.asp"
                "?FView=list"
                "&FKatID="
                "&sayfa=1"
                f"&FAdi={requests.utils.quote(urun_kodu)}"
                "&F=Ara"
                "&Sirala=Yok"
            )

            cevap = guvenli_get(
                url
            )

            soup = BeautifulSoup(
                cevap.text,
                "html.parser"
            )

            # Önce tam ID eşleşmesi
            satir = soup.find(
                "tr",
                id=urun_kodu
            )

            if satir:

                durum, miktar = stok_bul_html(
                    str(satir)
                )

                if miktar is not None:
                    return durum, miktar

            # Genel satırlar içinde kodu ara
            for aday in soup.select(
                "tr.urun-klavye-satiri[id]"
            ):

                kod = temiz_metin(
                    aday.get("id", "")
                )

                if kod == urun_kodu:

                    durum, miktar = stok_bul_html(
                        str(aday)
                    )

                    if miktar is not None:
                        return durum, miktar

            # Bulunamadıysa stok kapalı kabul edilir.
            return "BILINMIYOR", 0

        except Exception as e:

            print(
                f"{urun_kodu}: stok arama "
                f"{no}/{STOK_DENEME} hata: {e}"
            )

            if no < STOK_DENEME:

                try:
                    giris_yap()
                except Exception:
                    pass

                time.sleep(
                    min(no * 2, 8)
                )

    return "BILINMIYOR", 0


# ============================================================
# TÜM DETAYLARI ÇEK
# ============================================================

urunler = []
hatalar = []

kod_listesi = list(
    urun_kayitlari.keys()
)

toplam = len(
    kod_listesi
)

print("")
print("====================================")
print("ÜRÜN DETAYLARI ÇEKİLİYOR")
print("====================================")


for sira, urun_kodu in enumerate(
    kod_listesi,
    start=1
):

    try:
        kayit = urun_kayitlari[
            urun_kodu
        ]

        # ----------------------------------------------------
        # UZUN ÇALIŞMADA PROAKTİF YENİ GİRİŞ
        # ----------------------------------------------------

        if (
            sira > 1
            and sira % YENIDEN_GIRIS_ARALIGI == 0
        ):
            print(
                f"{sira}/{toplam}: "
                "periyodik yeniden giriş..."
            )

            giris_yap()

            time.sleep(1)


        # ----------------------------------------------------
        # STOK
        # ----------------------------------------------------

        stok_durumu, xml_stok = stok_bul_html(
            kayit.get(
                "stok_html",
                ""
            )
        )

        # Liste HTML'inde stok bilinmiyorsa
        # kodla ayrı arama yap.
        if xml_stok is None:

            stok_durumu, xml_stok = stok_ara(
                urun_kodu
            )


        # ----------------------------------------------------
        # DETAY MODALI
        # ----------------------------------------------------

        modal = guvenli_modal(
            urun_kodu
        )

        modal_soup = BeautifulSoup(
            modal.text,
            "html.parser"
        )


        # ----------------------------------------------------
        # ÜRÜN ADI
        # ----------------------------------------------------

        baslik = modal_soup.find(
            "h5"
        )

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


        # ----------------------------------------------------
        # MODAL TABLO ALANLARI
        # ----------------------------------------------------

        alanlar = {}

        for detay_satiri in modal_soup.select(
            "table tr"
        ):

            th = detay_satiri.find(
                "th"
            )

            td = detay_satiri.find(
                "td"
            )

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

            alanlar[
                anahtar
            ] = deger


        # ----------------------------------------------------
        # FİYAT
        # ----------------------------------------------------

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

        # 0.00 parse hatasına karşı
        if bayi_fiyati == "0.00":

            # Kaynak gerçekten 0 ise kabul edilebilir,
            # fakat boş/bozuk fiyat ise hata sayalım.
            fiyat_rakam = re.search(
                r"\d",
                bayi_fiyati_raw
            )

            if fiyat_rakam:
                pass
            else:
                raise Exception(
                    f"Bayi fiyatı parse edilemedi: "
                    f"{bayi_fiyati_raw}"
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


        # ----------------------------------------------------
        # AÇIKLAMA
        # ----------------------------------------------------

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


        # ----------------------------------------------------
        # GÖRSELLER
        # ----------------------------------------------------

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

        # Entegra alanımız ilk 4 görsel
        gorseller = gorseller[:4]


        # ----------------------------------------------------
        # BARKOD
        # ----------------------------------------------------

        if urun_kodu in barkod_map:

            barkod = barkod_map[
                urun_kodu
            ]

        else:

            barkod = yeni_barkod_uret()

            barkod_map[
                urun_kodu
            ] = barkod


        # ----------------------------------------------------
        # MARKA
        # ----------------------------------------------------

        marka = ""

        if urun_adi:
            marka = urun_adi.split()[0]


        # ----------------------------------------------------
        # XML ÜRÜNÜ
        # ----------------------------------------------------

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


        # Logu gereksiz şişirmemek için
        # her 20 üründe bir rapor.
        if (
            sira == 1
            or sira % 20 == 0
            or sira == toplam
        ):

            print(
                f"{sira}/{toplam} | "
                f"{urun_kodu} | "
                f"{stok_durumu}->{xml_stok} | "
                f"{bayi_fiyati} {para_birimi}"
            )


        time.sleep(
            URUN_BEKLEME
        )


    except Exception as e:

        hata = (
            f"{sira}/{toplam} | "
            f"{urun_kodu} | {e}"
        )

        hatalar.append(
            hata
        )

        print(
            "HATA:",
            hata
        )


# ============================================================
# HATA VARSA CANLI XML'E DOKUNMA
# ============================================================

if hatalar:

    print("")
    print("====================================")
    print("HATALI ÜRÜNLER")
    print("====================================")

    for hata in hatalar:
        print(
            hata
        )

    raise Exception(
        f"{len(hatalar)} üründe hata var. "
        "Canlı XML değiştirilmedi."
    )


if len(urunler) != toplam:

    raise Exception(
        f"Keşfedilen {toplam}, "
        f"hazırlanan {len(urunler)}. "
        "Ürün sayıları uyuşmuyor. "
        "Canlı XML değiştirilmedi."
    )


if len(urunler) < MIN_BEKLENEN_URUN:

    raise Exception(
        f"Yalnızca {len(urunler)} ürün hazırlandı. "
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
        f"    <currency>"
        f"{xml_metin(urun['currency'])}"
        f"</currency>"
    )

    xml_satirlari.append(
        f"    <price1>{urun['price1']}</price1>"
    )

    xml_satirlari.append(
        f"    <tax>{urun['tax']}</tax>"
    )

    xml_satirlari.append(
        f"    <barcode>"
        f"{xml_metin(urun['barcode'])}"
        f"</barcode>"
    )

    xml_satirlari.append(
        f"    <brand>"
        f"{xml_metin(urun['brand'])}"
        f"</brand>"
    )

    xml_satirlari.append(
        f"    <mainCategory>"
        f"{xml_metin(urun['mainCategory'])}"
        f"</mainCategory>"
    )

    xml_satirlari.append(
        f"    <category>"
        f"{xml_metin(urun['category'])}"
        f"</category>"
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
# XML DOĞRULAMA
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


if xml_urun_sayisi != len(
    urunler
):

    raise Exception(
        f"Geçici XML'de {xml_urun_sayisi}, "
        f"beklenen {len(urunler)} ürün. "
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
# TÜM İŞLEM BAŞARILIYSA CANLI XML
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

eur_sayisi = sum(
    1
    for urun in urunler
    if urun["currency"] == "EUR"
)

usd_sayisi = sum(
    1
    for urun in urunler
    if urun["currency"] == "USD"
)

trl_sayisi = sum(
    1
    for urun in urunler
    if urun["currency"] == "TRL"
)


print("")
print("====================================")
print("YAŞAR TEKNİK TÜM XML TAMAMLANDI")
print("====================================")

print(
    "Toplam ürün:",
    len(urunler)
)

print(
    "GENEL kaynak:",
    len(genel_urunler)
)

print(
    "Fiyat listesi kaynak:",
    len(fiyat_listesi_urunler)
)

print(
    "Stok açık (100):",
    stokta_var
)

print(
    "Stok kapalı (0):",
    kapali
)

print(
    "TRL:",
    trl_sayisi
)

print(
    "EUR:",
    eur_sayisi
)

print(
    "USD:",
    usd_sayisi
)

print(
    "Barkod sayısı:",
    len(barkod_map)
)

print(
    "XML:",
    XML_DOSYASI
)

print("====================================")
