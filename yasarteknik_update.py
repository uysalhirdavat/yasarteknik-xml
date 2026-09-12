import os
import requests

BASE_URL = "https://bayi.yasarteknik.com.tr"

MUSTERI_KODU = os.environ.get("YASAR_KULLANICI_ADI")
KULLANICI_KODU = os.environ.get("YASAR_KULLANICI_KODU")
SIFRE = os.environ.get("YASAR_SIFRE")

if not MUSTERI_KODU or not KULLANICI_KODU or not SIFRE:
    raise Exception("GitHub Secrets eksik!")

session = requests.Session()

login_url = f"{BASE_URL}/Login.asp"

data = {
    "KullaniciAdi": MUSTERI_KODU,
    "KullaniciKodu": KULLANICI_KODU,
    "Sifre": SIFRE
}

response = session.post(
    login_url,
    data=data,
    timeout=30
)

response.raise_for_status()

kontrol = session.get(
    f"{BASE_URL}/YeniSiparisGir.asp",
    timeout=30
)

kontrol.raise_for_status()

html = kontrol.text.lower()

if "login.asp" in kontrol.url.lower() or "müşteri kodu" in html and "parola" in html:
    raise Exception("Yaşar Teknik girişi başarısız!")

print("YAŞAR TEKNİK GİRİŞİ BAŞARILI")
print("Açılan sayfa:", kontrol.url)
