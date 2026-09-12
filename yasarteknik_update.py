import os
import requests

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

# Önce giriş sayfasını aç, oturum çerezi oluşsun
ilk = session.get(
    f"{BASE_URL}/Login.asp",
    timeout=30
)

ilk.raise_for_status()

print("Ilk GET:", ilk.status_code)

login_data = {
    "KullaniciAdi": MUSTERI_KODU,
    "KullaniciKodu": KULLANICI_KODU,
    "Sifre": SIFRE
}

login_headers = {
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/Login.asp",
    "X-Requested-With": "XMLHttpRequest"
}

# Yaşar Teknik'in gerçek AJAX giriş adresi
login = session.post(
    f"{BASE_URL}/ajax/Login.asp",
    data=login_data,
    headers=login_headers,
    timeout=30,
    allow_redirects=False
)

print("Login HTTP:", login.status_code)
print("Login cevap:", repr(login.text.strip()))
print("Yonlendirme:", login.headers.get("Location"))

# Başarılı girişte sunucu tam olarak "1" döndürüyor
if login.status_code != 200 or login.text.strip() != "1":
    raise Exception(
        "Yaşar Teknik giriş başarısız. "
        "GitHub Secrets içindeki Müşteri Kodu / Kullanıcı Kodu / Şifreyi kontrol edin."
    )

print("AJAX GIRIS BASARILI")

# Oturum gerçekten açıldı mı kontrol et
kontrol = session.get(
    f"{BASE_URL}/Default.asp",
    timeout=30,
    allow_redirects=True
)

kontrol.raise_for_status()

print("Kontrol URL:", kontrol.url)
print("Kontrol HTTP:", kontrol.status_code)

html = kontrol.text.lower()

basarili = (
    "toplam borç" in html
    or "toplam borc" in html
    or "toplam alacak" in html
    or "bekleyen sipariş" in html
    or "bekleyen siparis" in html
    or "hızlı ürün ara" in html
    or "hizli urun ara" in html
)

if not basarili:
    raise Exception("Giriş cevabı 1 geldi fakat oturum doğrulanamadı!")

print("====================================")
print("YAŞAR TEKNİK GİRİŞİ TAM BAŞARILI")
print("====================================")
from bs4 import BeautifulSoup

# ============================================================
# ÜRÜN LİSTESİ TESTİ
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

print("Ürün sayfası HTTP:", urun_sayfasi.status_code)
print("Ürün sayfası URL:", urun_sayfasi.url)

soup = BeautifulSoup(urun_sayfasi.text, "html.parser")

urun_satirlari = soup.select("tr.urun-klavye-satiri")

print("Bulunan ürün sayısı:", len(urun_satirlari))

if not urun_satirlari:
    raise Exception("Ürün listesinde ürün bulunamadı!")

print("====================================")
print("İLK SAYFADAKİ ÜRÜNLER")
print("====================================")

for sira, satir in enumerate(urun_satirlari[:20], start=1):

    urun_kodu = satir.get("id", "").strip()

    hucreler = satir.find_all("td")

    urun_adi = ""

    if len(hucreler) >= 3:
        urun_adi = hucreler[2].get_text(
            " ",
            strip=True
        )

    print(
        f"{sira}. "
        f"Kod: {urun_kodu} | "
        f"Ürün: {urun_adi}"
    )

print("====================================")
print("ÜRÜN LİSTESİ TESTİ BAŞARILI")
print("====================================")
# ============================================================
# TEK ÜRÜN DETAY TESTİ
# ============================================================

print("")
print("====================================")
print("TEK ÜRÜN DETAY TESTİ")
print("====================================")

ilk_satir = urun_satirlari[0]

urun_kodu = ilk_satir.get("id", "").strip()

print("Test ürün kodu:", urun_kodu)

# ------------------------------------------------------------
# LİSTEDEKİ STOK DURUMUNU OKU
# ------------------------------------------------------------

stok_durumu = "BILINMIYOR"

stok_hucreleri = ilk_satir.find_all("td")

for hucre in stok_hucreleri:
    style = hucre.get("style", "").lower()
    title = hucre.get("title", "").lower()
    data_title = hucre.get("data-bs-title", "").lower()

    metin = " ".join([
        hucre.get_text(" ", strip=True).lower(),
        title,
        data_title,
        style
    ])

    # Yaşar Teknik renkleri
    if "#1ab394" in metin or "stokta var" in metin:
        stok_durumu = "STOKTA_VAR"
        break

    if "kritik stok" in metin or "orange" in metin:
        stok_durumu = "KRITIK"
        break

    if "stokta yok" in metin or "red" in metin:
        stok_durumu = "STOKTA_YOK"
        break

print("Stok durumu:", stok_durumu)

# Bizim XML stok kuralımız
if stok_durumu == "STOKTA_VAR":
    xml_stok = 100
else:
    xml_stok = 0

print("XML'e gönderilecek stok:", xml_stok)

# ------------------------------------------------------------
# ÜRÜN DETAY MODALINI ÇEK
# ------------------------------------------------------------

modal_url = f"{BASE_URL}/ajax/Urun_ModalGoster.asp"

modal = session.post(
    modal_url,
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

print("Modal HTTP:", modal.status_code)

modal_soup = BeautifulSoup(modal.text, "html.parser")

# ------------------------------------------------------------
# ÜRÜN ADI
# ------------------------------------------------------------

baslik = modal_soup.find("h5")

urun_adi = baslik.get_text(
    " ",
    strip=True
) if baslik else ""

print("Ürün adı:", urun_adi)

# ------------------------------------------------------------
# TABLO ALANLARINI OKU
# ------------------------------------------------------------

alanlar = {}

for satir in modal_soup.select("table tr"):

    th = satir.find("th")
    td = satir.find("td")

    if not th or not td:
        continue

    alan_adi = th.get_text(
        " ",
        strip=True
    )

    alan_degeri = td.get_text(
        " ",
        strip=True
    )

    alanlar[alan_adi] = alan_degeri

print("Ürün kodu:", alanlar.get("Ürün Kodu", ""))
print("Liste fiyatı:", alanlar.get("Liste Fiyatı", ""))
print("Bayi fiyatı:", alanlar.get("Bayi Fiyatı", ""))
print("KDV:", alanlar.get("KDV", ""))
print("Birim:", alanlar.get("Birim", ""))
print(
    "Minimum sipariş:",
    alanlar.get("Minimum Sipariş Miktarı", "")
)
print(
    "Koli miktarı:",
    alanlar.get("Koli Miktarı", "")
)
print(
    "Paket miktarı:",
    alanlar.get("Paket Miktarı", "")
)

# ------------------------------------------------------------
# PARA BİRİMİ
# ------------------------------------------------------------

bayi_fiyati_raw = alanlar.get("Bayi Fiyatı", "")

para_birimi = "TRL"

fiyat_upper = bayi_fiyati_raw.upper()

if "EUR" in fiyat_upper or "€" in bayi_fiyati_raw:
    para_birimi = "EUR"

elif "USD" in fiyat_upper or "$" in bayi_fiyati_raw:
    para_birimi = "USD"

elif "TL" in fiyat_upper or "₺" in bayi_fiyati_raw:
    para_birimi = "TRL"

print("Para birimi:", para_birimi)

# ------------------------------------------------------------
# GÖRSELLER
# ------------------------------------------------------------

gorseller = []

for img in modal_soup.select(
    "#mainCarousel img"
):

    src = img.get("src", "").strip()

    if src and src not in gorseller:
        gorseller.append(src)

print("Görsel sayısı:", len(gorseller))

for no, url in enumerate(
    gorseller,
    start=1
):
    print(
        f"Görsel {no}:",
        url
    )

# ------------------------------------------------------------
# AÇIKLAMA
# ------------------------------------------------------------

aciklama_alani = modal_soup.select_one(
    "#home"
)

if aciklama_alani:
    aciklama_html = aciklama_alani.decode_contents().strip()
else:
    aciklama_html = ""

print(
    "Açıklama uzunluğu:",
    len(aciklama_html)
)

print("")
print("====================================")
print("TEK ÜRÜN DETAY TESTİ BAŞARILI")
print("====================================")
