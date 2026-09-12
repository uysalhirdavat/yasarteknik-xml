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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Referer": f"{BASE_URL}/Login.asp",
    "Origin": BASE_URL,
    "X-Requested-With": "XMLHttpRequest"
})

login_data = {
    "KullaniciAdi": MUSTERI_KODU,
    "KullaniciKodu": KULLANICI_KODU,
    "Sifre": SIFRE
}

login = session.post(
    f"{BASE_URL}/Login.asp",
    data=login_data,
    timeout=30,
    allow_redirects=True
)

login.raise_for_status()

print("Login HTTP:", login.status_code)
print("Login cevap:", login.text[:200].strip())

kontrol = session.get(
    f"{BASE_URL}/Default.asp",
    timeout=30,
    allow_redirects=True
)

kontrol.raise_for_status()

print("Kontrol URL:", kontrol.url)
print("Kontrol HTTP:", kontrol.status_code)

html = kontrol.text.lower()

# Giriş yapılmış ana sayfada görünen karakteristik alanlar
basarili = (
    "toplam borç" in html
    or "toplam borc" in html
    or "bekleyen sipariş" in html
    or "bekleyen siparis" in html
    or "hızlı ürün ara" in html
    or "hizli urun ara" in html
)

if not basarili:
    print("Kontrol sayfasinin ilk 500 karakteri:")
    print(kontrol.text[:500])
    raise Exception("Yaşar Teknik girişi doğrulanamadı!")

print("YAŞAR TEKNİK GİRİŞİ BAŞARILI")
