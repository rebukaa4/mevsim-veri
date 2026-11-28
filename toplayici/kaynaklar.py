"""Kaynak okuyucuları: her kaynak için küçük bir indirici + ayrıştırıcı.

Ayrıştırıcılar ağdan bağımsızdır (testler kayıtlı örnek dosyalarla çalışır).
Fiyatlar okunur ama SAKLANMAZ: yalnızca kalem adları ve "liste bir önceki günün aynısı mı?"
kontrolü için bir özet (hash) tutulur. Uygulamada fiyat yoktur.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime


class KaynakHatasi(Exception):
    """Kaynak okunamadı ya da yapısı değişmiş."""


@dataclass
class Yanit:
    url: str
    http: int | None
    govde: bytes


@dataclass
class Gozlem:
    """Bir kaynağın bir günlük listesi (ad + etiket; fiyat yok)."""
    kaynak: str
    tarih: str                      # verinin ait olduğu gün (YYYY-MM-DD)
    adlar: list[str] = field(default_factory=list)
    ozet: str | None = None         # liste (ad + değerler) özeti; taşınmış gün tespiti için
    bos: bool = False
    ek: dict = field(default_factory=dict)

    def kayit(self) -> dict:
        d = {"k": self.kaynak, "t": self.tarih}
        if self.bos:
            d["bos"] = True
        else:
            d["ozet"] = self.ozet
            d["adlar"] = self.adlar
        d.update(self.ek)
        return d


def indir(url: str, ayar: dict) -> Yanit:
    """GET isteği; ağ hatasında (ör. geçici DNS sorunu) 10 sn sonra bir kez daha denenir."""
    try:
        return _indir(url, ayar)
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        import time
        time.sleep(10)
        return _indir(url, ayar)


def _indir(url: str, ayar: dict) -> Yanit:
    """Tek GET isteği; zaman aşımı ve nazik kullanıcı adı ile. 204 boş gövde döner."""
    istek = urllib.request.Request(url, headers={
        "User-Agent": ayar["kullanici_araci"],
        "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
    })
    try:
        with urllib.request.urlopen(istek, timeout=ayar["zaman_asimi_sn"]) as r:
            return Yanit(url, r.status, r.read())
    except urllib.error.HTTPError as e:
        return Yanit(url, e.code, b"")


def _ozet(parcalar) -> str:
    return hashlib.sha1(json.dumps(sorted(parcalar), ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# Ad normalleştirme
# --------------------------------------------------------------------------
_HARF = str.maketrans({"Ş": "S", "Ğ": "G", "Ü": "U", "Ö": "O", "Ç": "C", "Â": "A", "Î": "I", "Û": "U"})
ETIKETLER = {"SERA", "TARLA", "ITHAL", "KULTUR", "DONUK", "DENIZ", "TATLI", "YEM"}


def normal(ad: str) -> str:
    """'ARMUT  DEVECI', 'Armut Deveci', 'ARMUT DEVECİ' -> 'ARMUT DEVECI'; 'LEVREK ( KÜLTÜR )' -> 'LEVREK (KULTUR)'."""
    s = (ad or "").replace("İ", "I").replace("ı", "I").replace("i", "I").upper().translate(_HARF)
    s = re.sub(r"\s*\(\s*", " (", s)
    s = re.sub(r"\s*\)", ")", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def etiketler(normal_ad: str) -> set[str]:
    return {w for w in re.split(r"[^A-Z]+", normal_ad) if w in ETIKETLER}


def _tip_eki(tip: str | None) -> str:
    """İzmir 'MalTipAdi' alanı: İTHAL / KÜLTÜR / TATLI SU / İTHAL (DONUK) -> ada '#ITHAL' gibi eklenir."""
    t = normal(tip or "")
    ek = [e for e in ("ITHAL", "KULTUR", "TATLI", "DONUK") if e in t]
    return (" #" + " ".join(ek)) if ek else ""


def ad_parcala(saklanan: str) -> str:
    """Saklanan ad 'ANANAS #ITHAL' ise eşleştirme için 'ANANAS' döner."""
    return saklanan.split(" #", 1)[0]


# --------------------------------------------------------------------------
# İzmir BB hal API'leri (sebze-meyve ve balık) — CC BY 4.0
# --------------------------------------------------------------------------
IZMIR_URL = {
    "izmir_sebze_meyve": "https://openapi.izmir.bel.tr/api/ibb/halfiyatlari/sebzemeyve/{tarih}",
    "izmir_balik": "https://openapi.izmir.bel.tr/api/ibb/halfiyatlari/balik/{tarih}",
}


def izmir_ayristir(kaynak: str, istenen_tarih: str, http: int | None, govde: bytes) -> Gozlem:
    if http == 204 or (http == 200 and not govde.strip()):
        return Gozlem(kaynak, istenen_tarih, bos=True)       # hafta sonu / bayram / henüz yayımlanmadı
    if http != 200:
        raise KaynakHatasi(f"HTTP {http}")
    try:
        veri = json.loads(govde.decode("utf-8-sig"))
    except ValueError as e:
        raise KaynakHatasi(f"JSON okunamadı: {e}") from None
    liste = veri.get("HalFiyatListesi") if isinstance(veri, dict) else None
    if not isinstance(liste, list):
        raise KaynakHatasi("yapı değişmiş: 'HalFiyatListesi' yok")
    if not liste:
        return Gozlem(kaynak, istenen_tarih, bos=True)
    adlar, parcalar = [], []
    for x in liste:
        if not isinstance(x, dict) or not isinstance(x.get("MalAdi"), str):
            raise KaynakHatasi("yapı değişmiş: 'MalAdi' alanı yok")
        ad = normal(x["MalAdi"]) + _tip_eki(x.get("MalTipAdi"))
        adlar.append(ad)
        parcalar.append([ad, x.get("AsgariUcret"), x.get("AzamiUcret"), x.get("OrtalamaUcret")])
    bulten = str(veri.get("BultenTarihi") or "")[:10]
    g = Gozlem(kaynak, istenen_tarih, sorted(set(adlar)), _ozet(parcalar))
    if bulten and bulten != istenen_tarih:
        g.ek["bulten"] = bulten                                 # başka günün bülteni: taşınmış sayılır
    return g


# --------------------------------------------------------------------------
# Konya BB hal listesi (HTML)
# --------------------------------------------------------------------------
KONYA_URL = "https://www.konya.bel.tr/hal-fiyatlari"


def konya_ayristir(http: int | None, govde: bytes) -> Gozlem:
    if http != 200:
        raise KaynakHatasi(f"HTTP {http}")
    t = govde.decode("utf-8", errors="replace")
    m = re.search(r'<option value="(\d{4}-\d{2}-\d{2})"\s+selected', t)
    if not m:
        m2 = re.search(r"(\d{2})\.(\d{2})\.(\d{4}) Tarihli Meyve-Sebze", t)
        if not m2:
            raise KaynakHatasi("yapı değişmiş: liste tarihi bulunamadı")
        tarih = f"{m2.group(3)}-{m2.group(2)}-{m2.group(1)}"
    else:
        tarih = m.group(1)
    satirlar = re.findall(r"<tr>\s*<td>([^<]+)</td>\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>", t)
    if not satirlar:
        raise KaynakHatasi("yapı değişmiş: tablo satırı bulunamadı")
    adlar = sorted({normal(html.unescape(s[0])) for s in satirlar})
    return Gozlem("konya", tarih, adlar, _ozet([[normal(html.unescape(s[0])), s[2].strip(), s[3].strip()] for s in satirlar]))


# --------------------------------------------------------------------------
# Hal Kayıt Sistemi — yalnızca ilk sayfa (form gönderimi YOK)
# --------------------------------------------------------------------------
HKS_URL = "https://www.hal.gov.tr/Sayfalar/FiyatDetaylari.aspx"


def _sayi(metin: str) -> float:
    s = metin.strip().replace(".", "").replace(",", ".")
    return float(s) if s else 0.0


def hks_ayristir(http: int | None, govde: bytes) -> Gozlem:
    if http != 200:
        raise KaynakHatasi(f"HTTP {http}")
    t = govde.decode("utf-8", errors="replace")
    m = re.search(r"\((\d{2})\.(\d{2})\.(\d{4}) Tarihli Veriler", t)
    if not m:
        raise KaynakHatasi("yapı değişmiş: bülten tarihi bulunamadı")
    tarih = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    i = t.find("gvFiyatlar")
    if i < 0:
        raise KaynakHatasi("yapı değişmiş: fiyat tablosu bulunamadı")
    satirlar = re.findall(
        r"<tr>\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>.*?_lbl4\"[^>]*>([^<]*)</span>",
        t[i:], re.S)
    if not satirlar:
        raise KaynakHatasi("yapı değişmiş: tablo satırı bulunamadı")
    hacim: dict[str, float] = {}
    for ad, _cins, _tur, miktar in satirlar:
        n = normal(html.unescape(ad))
        hacim[n] = hacim.get(n, 0.0) + _sayi(miktar)
    g = Gozlem("hks", tarih, sorted(hacim), _ozet([[k, v] for k, v in hacim.items()]))
    g.ek["hacim"] = {k: round(v) for k, v in sorted(hacim.items())}
    return g


# --------------------------------------------------------------------------
# Resmî Gazete günlük fihrist (windows-1254)
# --------------------------------------------------------------------------
RG_URL = "https://www.resmigazete.gov.tr/eskiler/{y}/{m}/{ymd}.htm"


def rg_url(gun: date) -> str:
    return RG_URL.format(y=gun.strftime("%Y"), m=gun.strftime("%m"), ymd=gun.strftime("%Y%m%d"))


def rg_ayristir(gun: date, http: int | None, govde: bytes) -> list[dict]:
    """Fihristteki karar/tebliğ başlıkları ve bağlantıları: [{'baslik','link'}]."""
    if http != 200:
        raise KaynakHatasi(f"HTTP {http}")
    t = govde.decode("cp1254", errors="replace")
    ymd = gun.strftime("%Y%m%d")
    taban = f"https://www.resmigazete.gov.tr/eskiler/{gun:%Y}/{gun:%m}/"
    sonuc = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', t, re.S):
        link = m.group(1).strip()
        if not re.match(rf"(?:.*/)?{ymd}(?:M\d+)?-\d+\.(?:htm|pdf)$", link):
            continue
        baslik = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", m.group(2)))).strip(" –-")
        if baslik:
            sonuc.append({"baslik": baslik, "link": link if link.startswith("http") else taban + link.split("/")[-1]})
    if not sonuc:
        raise KaynakHatasi("yapı değişmiş ya da sayı yayımlanmamış: fihristte başlık bulunamadı")
    return sonuc


def rg_eslesenler(basliklar: list[dict], kaliplar: list[str]) -> list[dict]:
    derli = [re.compile(k, re.I) for k in kaliplar]
    cikti = []
    for b in basliklar:
        kucuk = b["baslik"].replace("İ", "i").replace("I", "ı").lower()
        if any(k.search(kucuk) or k.search(b["baslik"]) for k in derli):
            cikti.append(b)
    return cikti


def bugun_tr() -> date:
    """Türkiye saatiyle bugün (UTC+3, yaz saati uygulaması yok)."""
    from datetime import timedelta, timezone
    return datetime.now(timezone(timedelta(hours=3))).date()
