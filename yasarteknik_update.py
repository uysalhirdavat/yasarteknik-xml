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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
})

# 1) Önce giriş sayfasını aç.
# Böylece ASPSESSION çerezi oluşsun.
ilk = session.get(
    f"{BASE_URL}/Login.asp",
    timeout=30
)

ilk.raise_for_status()

print("Ilk GET:", ilk.status_code)
print("Ilk cookie sayisi:", len(session.cookies))

# 2) Tarayıcıdaki form ile aynı alanları gönder
login_data = {
    "KullaniciAdi": MUSTERI_KODU,
    "KullaniciKodu": KULLANICI_KODU,
    "Sifre": SIFRE,
}

login_headers = {
    "Referer": f"{BASE_URL}/Login.asp",
    "Origin": BASE_URL,
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

login = session.post(
    f"{BASE_URL}/Login.asp",
    data=login_data,
    headers=login_headers,
    timeout=30,
    allow_redirects=True,
)

login.raise_for_status()

print("Login HTTP:", login.status_code)
print("Login son URL:", login.url)
print("Login cevap ilk 200:", login.text[:200].replace("\n", " "))

# 3) Giriş yapıldı mı kontrol et
kontrol = session.get(
    f"{BASE_URL}/Default.asp",
    timeout=30,
    allow_redirects=True,
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
    print("Kontrol ilk 300:", kontrol.text[:300].replace("\n", " "))
    raise Exception("Yaşar Teknik girişi doğrulanamadı!")

print("YAŞAR TEKNİK GİRİŞİ BAŞARILI")
