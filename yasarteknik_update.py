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
PARCA_DOSYASI = "yasarteknik_partial.json"
BARKOD_PREFIX = "uyl12092026999"
MIN_BEKLENEN_URUN = 8000
MAX_SAYFA = 300
PARCA_BOYUTU = int(os.environ.get("YASAR_CHUNK_SIZE", "1200"))
GET_DENEME = 6
MODAL_DENEME = 6
STOK_DENEME = 5
LISTE_BEKLEME = 0.08
URUN_BEKLEME = 0.05
YENIDEN_GIRIS_ARALIGI = 300

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

def temiz_metin(deger):
    if deger is None:
        return ""
    return " ".join(str(deger).replace("\xa0", " ").split()).strip()

def xml_gecerli_karakterleri_temizle(deger):
    if deger is None:
        return ""

    metin = str(deger)

    return "".join(
        karakter
        for karakter in metin
        if (
            karakter == "\t"
            or karakter == "\n"
            or karakter == "\r"
            or 0x20 <= ord(karakter) <= 0xD7FF
            or 0xE000 <= ord(karakter) <= 0xFFFD
            or 0x10000 <= ord(karakter) <= 0x10FFFF
        )
    )


def xml_metin(deger):
    temiz = xml_gecerli_karakterleri_temizle(
        temiz_metin(deger)
    )

    return escape(
        temiz,
        {
            '"': "&quot;",
            "'": "&apos;"
        }
    )


def cdata_temizle(deger):
    temiz = xml_gecerli_karakterleri_temizle(deger)

    return temiz.replace(
        "]]>",
        "]]]]><![CDATA[>"
    )


def turk_fiyat_to_xml(deger):
    if not deger:
        return "0.00"
    fiyat = str(deger)
    fiyat = (
        fiyat.replace("\xa0", " ")
        .replace("TRY", "").replace("TRL", "").replace("TL", "")
        .replace("EUR", "").replace("USD", "")
        .replace("€", "").replace("$", "").replace("₺", "").strip()
    )
    fiyat = re.sub(r"[^0-9,.\-]", "", fiyat)
    if "," in fiyat:
        fiyat = fiyat.replace(".", "").replace(",", ".")
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
    m = re.search(r"(\d+)", str(kdv))
    return m.group(1) if m else "20"

def stok_bul_html(html):
    html = str(html).lower()
    if "#1ab394" in html:
        return "STOKTA_VAR", 100
    if "#f8ac59" in html or "orange" in html or "kritik stok" in html:
        return "KRITIK", 0
    if "#ed5565" in html or "red" in html or "stokta yok" in html:
        return "STOKTA_YOK", 0
    return "BILINMIYOR", None

def json_yaz(path, veri):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)

def giris_yap():
    session.cookies.clear()
    ilk = session.get(f"{BASE_URL}/Login.asp", timeout=30)
    ilk.raise_for_status()
    login = session.post(
        f"{BASE_URL}/ajax/Login.asp",
        data={
            "KullaniciAdi": MUSTERI_KODU,
            "KullaniciKodu": KULLANICI_KODU,
            "Sifre": SIFRE,
        },
        headers={
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/Login.asp",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
        allow_redirects=False,
    )
    if login.status_code != 200 or login.text.strip() != "1":
        raise Exception("Yaşar Teknik giriş başarısız!")
    print("YAŞAR TEKNİK GİRİŞİ BAŞARILI")

def guvenli_get(url, deneme=GET_DENEME):
    son_hata = None
    for no in range(1, deneme + 1):
        try:
            r = session.get(url, timeout=45, allow_redirects=True)
            u = r.url.lower()
            if "login.asp" in u or "logout.asp" in u:
                print(f"GET oturum düştü ({no}/{deneme}), yeniden giriş...")
                giris_yap()
                time.sleep(min(no * 2, 8))
                continue
            r.raise_for_status()
            return r
        except Exception as e:
            son_hata = e
            print(f"GET hata {no}/{deneme}: {e}")
            if no < deneme:
                try:
                    giris_yap()
                except Exception as le:
                    print("Yeniden giriş uyarısı:", le)
                time.sleep(min(no * 2, 10))
    raise son_hata

def guvenli_modal(urun_kodu, deneme=MODAL_DENEME):
    son_hata = None
    for no in range(1, deneme + 1):
        try:
            r = session.post(
                f"{BASE_URL}/ajax/Urun_ModalGoster.asp",
                data={"ID": urun_kodu},
                headers={
                    "Referer": f"{BASE_URL}/YeniSiparisGir.asp",
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=45,
                allow_redirects=True,
            )
            u = r.url.lower()
            if "logout.asp" in u or "login.asp" in u:
                print(f"{urun_kodu}: modal oturumu düştü ({no}/{deneme})")
                giris_yap()
                time.sleep(min(no * 2, 8))
                continue
            r.raise_for_status()
            kontrol = r.text.lower()
            if (
                "<title>oturum aç" in kontrol
                or 'name="kullaniciadi"' in kontrol
                or "/login.asp" in kontrol[:2000]
            ):
                giris_yap()
                time.sleep(min(no * 2, 8))
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            if not (soup.find("h5") or soup.select_one("#mainCarousel") or soup.select_one("table")):
                raise Exception("Ürün modal içeriği doğrulanamadı")
            return r
        except Exception as e:
            son_hata = e
            print(f"{urun_kodu}: modal hata {no}/{deneme}: {e}")
            if no < deneme:
                try:
                    giris_yap()
                except Exception as le:
                    print("Yeniden giriş uyarısı:", le)
                time.sleep(min(no * 3, 15))
    raise Exception(f"{urun_kodu} modal alınamadı: {son_hata}")

def sayfadaki_kodlari_bul(html):
    soup = BeautifulSoup(html, "html.parser")
    kodlar, satir_map = [], {}
    for satir in soup.select("tr.urun-klavye-satiri[id]"):
        kod = temiz_metin(satir.get("id", ""))
        if kod and kod not in satir_map:
            kodlar.append(kod)
            satir_map[kod] = str(satir)
    desenler = [
        r'''UrunModalGoster\(\s*['"]([^'"]+)['"]''',
        r'''UrunModalGost(?:er|eri)\(\s*['"]([^'"]+)['"]''',
        r'''data-item-code\s*=\s*['"]([^'"]+)['"]''',
        r'''data-product-code\s*=\s*['"]([^'"]+)['"]''',
    ]
    for desen in desenler:
        for m in re.finditer(desen, html, flags=re.IGNORECASE):
            kod = temiz_metin(m.group(1))
            if kod and kod not in kodlar:
                kodlar.append(kod)
    return kodlar, satir_map

# Barkod haritası
barkod_map = {}
if os.path.exists(BARKOD_MAP_DOSYASI):
    with open(BARKOD_MAP_DOSYASI, "r", encoding="utf-8") as f:
        barkod_map = json.load(f)

if os.path.exists(XML_DOSYASI):
    try:
        root = ET.parse(XML_DOSYASI).getroot()
        for item in root.findall(".//item"):
            kod = temiz_metin(item.findtext("code") or item.findtext("id"))
            barkod = temiz_metin(item.findtext("barcode"))
            if kod and barkod and kod not in barkod_map:
                barkod_map[kod] = barkod
    except Exception as e:
        print("Eski XML barkod okuma uyarısı:", e)

kullanilan_barkodlar = set(barkod_map.values())
def yeni_barkod_uret():
    sayac = 1
    while True:
        barkod = BARKOD_PREFIX + f"{sayac:03d}"
        if barkod not in kullanilan_barkodlar:
            kullanilan_barkodlar.add(barkod)
            return barkod
        sayac += 1

giris_yap()
kontrol = guvenli_get(f"{BASE_URL}/Default.asp")
kh = kontrol.text.lower()
if not any(x in kh for x in ["toplam borç", "toplam borc", "toplam alacak", "bekleyen sipariş", "bekleyen siparis", "hızlı ürün ara", "hizli urun ara"]):
    raise Exception("Yaşar Teknik oturumu doğrulanamadı")

# Katalog keşfi
urun_kayitlari = {}
genel_urunler = set()
fiyat_listesi_urunler = set()

def urun_ekle(kod, kaynak, satir_html=""):
    if not kod:
        return
    if kod not in urun_kayitlari:
        urun_kayitlari[kod] = {"kod": kod, "kaynaklar": [], "stok_html": ""}
    if kaynak not in urun_kayitlari[kod]["kaynaklar"]:
        urun_kayitlari[kod]["kaynaklar"].append(kaynak)
    if satir_html and kaynak == "GENEL":
        urun_kayitlari[kod]["stok_html"] = satir_html
    elif satir_html and not urun_kayitlari[kod]["stok_html"]:
        urun_kayitlari[kod]["stok_html"] = satir_html

print("\n=== GENEL ÜRÜN LİSTESİ ===")
onceki = None
for sayfa in range(1, MAX_SAYFA + 1):
    url = (
        f"{BASE_URL}/YeniSiparisGir.asp?FView=list&FKatID=&sayfa={sayfa}"
        "&FAdi=&F=Ara&Sirala=Yok"
    )
    r = guvenli_get(url)
    kodlar, satir_map = sayfadaki_kodlari_bul(r.text)
    if not kodlar:
        break
    imza = tuple(kodlar)
    if onceki is not None and imza == onceki:
        break
    onceki = imza
    for kod in kodlar:
        genel_urunler.add(kod)
        urun_ekle(kod, "GENEL", satir_map.get(kod, ""))
    print(f"GENEL {sayfa}: {len(kodlar)} | toplam {len(urun_kayitlari)}")
    time.sleep(LISTE_BEKLEME)

print("\n=== FİYAT LİSTESİ ===")
onceki = None
for sayfa in range(1, MAX_SAYFA + 1):
    url = (
        f"{BASE_URL}/FiyatListesi.asp?sayfa={sayfa}"
        "&F=&FAdi=&FHizliFirsat=&FHizliInsert=&Sirala="
    )
    r = guvenli_get(url)
    kodlar, satir_map = sayfadaki_kodlari_bul(r.text)
    if not kodlar:
        break
    imza = tuple(kodlar)
    if onceki is not None and imza == onceki:
        break
    onceki = imza
    for kod in kodlar:
        fiyat_listesi_urunler.add(kod)
        urun_ekle(kod, "FIYAT_LISTESI", satir_map.get(kod, ""))
    print(f"FIYAT {sayfa}: {len(kodlar)} | toplam {len(urun_kayitlari)}")
    time.sleep(LISTE_BEKLEME)

kod_listesi = list(urun_kayitlari.keys())
toplam = len(kod_listesi)
print(f"\nTOPLAM BENZERSİZ: {toplam}")
if toplam < MIN_BEKLENEN_URUN:
    raise Exception(f"Yalnızca {toplam} ürün bulundu; canlı XML değiştirilmedi")

# Önceki parça
partial = {}
if os.path.exists(PARCA_DOSYASI):
    with open(PARCA_DOSYASI, "r", encoding="utf-8") as f:
        partial = json.load(f)
    if not isinstance(partial, dict):
        raise Exception("Partial dosyası bozuk")

mevcut_kodlar = set(kod_listesi)
partial = {k: v for k, v in partial.items() if k in mevcut_kodlar}
hazir_kodlar = set(partial.keys())
bekleyen = [k for k in kod_listesi if k not in hazir_kodlar]
bu_calismada = bekleyen[:PARCA_BOYUTU]

print("\n=== PARÇALI İŞLEM ===")
print("Toplam:", toplam)
print("Önceden hazır:", len(hazir_kodlar))
print("Bekleyen:", len(bekleyen))
print("Bu run:", len(bu_calismada))

def stok_ara(urun_kodu):
    for no in range(1, STOK_DENEME + 1):
        try:
            url = (
                f"{BASE_URL}/YeniSiparisGir.asp?FView=list&FKatID=&sayfa=1"
                f"&FAdi={requests.utils.quote(urun_kodu)}&F=Ara&Sirala=Yok"
            )
            r = guvenli_get(url)
            soup = BeautifulSoup(r.text, "html.parser")
            satir = soup.find("tr", id=urun_kodu)
            if satir:
                d, m = stok_bul_html(str(satir))
                if m is not None:
                    return d, m
            return "BILINMIYOR", 0
        except Exception as e:
            print(f"{urun_kodu}: stok arama {no}/{STOK_DENEME}: {e}")
            if no < STOK_DENEME:
                try:
                    giris_yap()
                except Exception:
                    pass
                time.sleep(min(no * 2, 8))
    return "BILINMIYOR", 0

def urunu_hazirla(urun_kodu):
    kayit = urun_kayitlari[urun_kodu]
    stok_durumu, xml_stok = stok_bul_html(kayit.get("stok_html", ""))
    if xml_stok is None:
        stok_durumu, xml_stok = stok_ara(urun_kodu)

    modal = guvenli_modal(urun_kodu)
    soup = BeautifulSoup(modal.text, "html.parser")
    baslik = soup.find("h5")
    urun_adi = temiz_metin(baslik.get_text(" ", strip=True)) if baslik else ""
    if not urun_adi:
        raise Exception("Ürün adı bulunamadı")

    alanlar = {}
    for tr in soup.select("table tr"):
        th, td = tr.find("th"), tr.find("td")
        if th and td:
            alanlar[temiz_metin(th.get_text(" ", strip=True))] = temiz_metin(td.get_text(" ", strip=True))

    bayi_raw = alanlar.get("Bayi Fiyatı", "")
    if not bayi_raw:
        raise Exception("Bayi fiyatı bulunamadı")
    fiyat = turk_fiyat_to_xml(bayi_raw)
    if fiyat == "0.00" and not re.search(r"\d", bayi_raw):
        raise Exception(f"Bayi fiyatı parse edilemedi: {bayi_raw}")

    aciklama_alani = soup.select_one("#home")
    aciklama = aciklama_alani.decode_contents().strip() if aciklama_alani else ""

    gorseller = []
    for img in soup.select("#mainCarousel img"):
        src = temiz_metin(img.get("src", ""))
        if src and src not in gorseller:
            gorseller.append(src)
    gorseller = gorseller[:4]

    if urun_kodu in barkod_map:
        barkod = barkod_map[urun_kodu]
    else:
        barkod = yeni_barkod_uret()
        barkod_map[urun_kodu] = barkod

    return {
        "id": urun_kodu,
        "code": urun_kodu,
        "label": urun_adi,
        "stock": xml_stok,
        "stok_durumu": stok_durumu,
        "details": aciklama,
        "currency": para_birimi_bul(bayi_raw),
        "price1": fiyat,
        "tax": kdv_bul(alanlar.get("KDV", "20")),
        "barcode": barkod,
        "brand": urun_adi.split()[0] if urun_adi else "",
        "mainCategory": "Yasar Teknik",
        "category": "Genel",
        "pictures": gorseller,
    }

hatalar = []
for i, kod in enumerate(bu_calismada, start=1):
    try:
        if i > 1 and i % YENIDEN_GIRIS_ARALIGI == 0:
            giris_yap()
            time.sleep(1)
        partial[kod] = urunu_hazirla(kod)
        if i == 1 or i % 20 == 0 or i == len(bu_calismada):
            u = partial[kod]
            print(f"{len(hazir_kodlar)+i}/{toplam} | {kod} | {u['stok_durumu']}->{u['stock']} | {u['price1']} {u['currency']}")
        if i % 100 == 0:
            json_yaz(PARCA_DOSYASI, partial)
            json_yaz(BARKOD_MAP_DOSYASI, barkod_map)
        time.sleep(URUN_BEKLEME)
    except Exception as e:
        hata = f"{kod} | {e}"
        hatalar.append(hata)
        print("HATA:", hata)

json_yaz(PARCA_DOSYASI, partial)
json_yaz(BARKOD_MAP_DOSYASI, barkod_map)

hazir_son = sum(1 for k in kod_listesi if k in partial)
kalan = toplam - hazir_son
print("\n=== PARÇA TAMAMLANDI ===")
print("Hazır:", hazir_son)
print("Kalan:", kalan)
print("Bu run hata:", len(hatalar))

if kalan > 0:
    print("XML henüz yayınlanmadı. İş akışını tekrar çalıştır.")
    raise SystemExit(0)

# Final XML
urunler = [partial[k] for k in kod_listesi]
xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<root>']
for u in urunler:
    xml.append("  <item>")
    xml.append(f"    <id>{xml_metin(u['id'])}</id>")
    xml.append(f"    <code>{xml_metin(u['code'])}</code>")
    xml.append(f"    <label>{xml_metin(u['label'])}</label>")
    xml.append(f"    <stock>{u['stock']}</stock>")
    xml.append("    <details><![CDATA[" + cdata_temizle(u['details']) + "]]></details>")
    xml.append(f"    <currency>{xml_metin(u['currency'])}</currency>")
    xml.append(f"    <price1>{u['price1']}</price1>")
    xml.append(f"    <tax>{u['tax']}</tax>")
    xml.append(f"    <barcode>{xml_metin(u['barcode'])}</barcode>")
    xml.append(f"    <brand>{xml_metin(u['brand'])}</brand>")
    xml.append(f"    <mainCategory>{xml_metin(u['mainCategory'])}</mainCategory>")
    xml.append(f"    <category>{xml_metin(u['category'])}</category>")
    for no, resim in enumerate(u['pictures'], start=1):
        xml.append(f"    <picture{no}>{xml_metin(resim)}</picture{no}>")
    xml.append("  </item>")
xml.append("</root>")

with open(GECICI_XML, "w", encoding="utf-8") as f:
    f.write("\n".join(xml))

root = ET.parse(GECICI_XML).getroot()
xml_sayisi = len(root.findall(".//item"))
if xml_sayisi != toplam or xml_sayisi < MIN_BEKLENEN_URUN:
    raise Exception(f"XML doğrulama hatası: {xml_sayisi}/{toplam}")

os.replace(GECICI_XML, XML_DOSYASI)
if os.path.exists(PARCA_DOSYASI):
    os.remove(PARCA_DOSYASI)
json_yaz(BARKOD_MAP_DOSYASI, barkod_map)

stokta_var = sum(1 for u in urunler if u['stock'] == 100)
kapali = sum(1 for u in urunler if u['stock'] == 0)
print("\n=== YAŞAR TEKNİK TÜM XML TAMAMLANDI ===")
print("Toplam ürün:", len(urunler))
print("Stok açık (100):", stokta_var)
print("Stok kapalı (0):", kapali)
print("Barkod sayısı:", len(barkod_map))
print("XML:", XML_DOSYASI)
