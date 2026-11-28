"""Sinyal kuralları (yalnızca kural tabanlı; yapay zekâ yok).

Temel takvim (kaynak/urunler/*.json) yalnızca OKUNUR; hiçbir kural onu değiştirmez.
Her kural bir "öneri" üretir: ne görüldüğünü söyler, neyi kanıtladığını değil.

Kurallar (eşikler ayarlar.json -> kurallar.<izmir|konya>):
  erken   (a) Halde göründü, takvimden erken
  yok     (b) Sezon başladı ama halde yok
  cekildi (c) Halden çekildi, takvim sürüyor
  uzadi   (c) Takvim bitti ama halde bol
HKS işlem hacmi (d) ve Konya (e, İzmir önerilerinde) yalnızca ikinci tanıktır; tek başına öneri açmaz.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from kaynaklar import ad_parcala, etiketler, normal

AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
DONEM_ADI = {"hasat": "hasat dönemi", "av": "av dönemi", "pazar_yogun": "pazarda yoğun bulunma dönemi", "depo": "depodan bulunma dönemi"}


def tr_tarih(g: date) -> str:
    return f"{g.day} {AYLAR[g.month - 1]} {g.year}"


def tr_gun_ay(g: date) -> str:
    return f"{g.day} {AYLAR[g.month - 1]}"


# --------------------------------------------------------------------------
# Eşleştirme
# --------------------------------------------------------------------------
@dataclass
class Kalem:
    ad: str
    urun_id: str
    yil_boyu_halde: bool


class Eslestirme:
    def __init__(self, bolum: dict, yil_boyu_oran: float, dislanan: list[str]):
        n = bolum.get("orneklem_gun_sayisi") or 0
        self.kalemler: dict[str, Kalem] = {}
        for k in bolum.get("kalemler", []):
            ad = normal(k["ad"])
            self.kalemler[ad] = Kalem(ad, k["urun_id"], bool(n) and k.get("orneklem", 0) / n >= yil_boyu_oran)
        self.yok_say = {normal(a) for a in bolum.get("yok_say", [])}
        self.dislanan = set(dislanan)

    def bul(self, saklanan: str) -> Kalem | None:
        return self.kalemler.get(ad_parcala(saklanan))

    def sinyal_kalemi(self, saklanan: str) -> Kalem | None:
        """Sinyalde sayılacak kalem: eşleşmiş, sera/ithal/kültür/donuk değil, yıl boyu halde değil."""
        k = self.bul(saklanan)
        if k is None or k.yil_boyu_halde or (etiketler(saklanan) & self.dislanan):
            return None
        return k

    def eslesmeyenler(self, adlar) -> list[str]:
        return sorted({a for a in adlar if ad_parcala(a) not in self.kalemler and ad_parcala(a) not in self.yok_say})


def eslestirme_yukle(yol: Path, ayar: dict) -> dict[str, Eslestirme]:
    veri = json.loads(Path(yol).read_text(encoding="utf-8"))
    dis = ayar.get("dislanan_etiketler", [])
    oran = {"konya": ayar["kurallar"]["konya"].get("yil_boyu_halde_oran", 0.8)}
    return {k: Eslestirme(veri[k], oran.get(k, ayar.get("yil_boyu_halde_oran", 0.9)), dis)
            for k in ("izmir_sebze_meyve", "izmir_balik", "konya", "hks") if k in veri}


# --------------------------------------------------------------------------
# Temel takvim
# --------------------------------------------------------------------------
def _gun(y: int, md: str) -> date:
    m, d = int(md[:2]), int(md[3:])
    try:
        return date(y, m, d)
    except ValueError:
        return date(y, m, 28)


@dataclass
class Satir:
    urun_id: str
    kapsam_turu: str
    kapsam_id: str
    donem_turu: str
    bas: str
    bit: str
    kaynak_adi: str
    kaynak_link: str | None
    guven: str

    def uzunluk(self) -> int:
        b, e = _gun(2001, self.bas), _gun(2001, self.bit)
        return ((e - b).days % 365) + 1

    def araliklar(self, etraf: date):
        """etraf tarihinin çevresindeki (önceki yıl, bu yıl, sonraki yıl) aralıklar."""
        for y in (etraf.year - 1, etraf.year, etraf.year + 1):
            s = _gun(y, self.bas)
            e = _gun(y, self.bit)
            if e < s:
                e = _gun(y + 1, self.bit)
            yield s, e


@dataclass
class UrunTakvimi:
    urun_id: str
    ad: str
    sezon: list[Satir] = field(default_factory=list)   # hasat/av/pazar_yogun (yıl boyu olmayan)
    depo: list[Satir] = field(default_factory=list)
    # Ürünün bu kapsamda yıl boyu satırları ve (balıkta) öteki denizlerin kayıtları: bunlardan biri
    # bugünü kapsıyorsa "erken" ve "uzadı" kuralları çalışmaz (İzmir balık hali her denizden balık satar).
    baska: list[Satir] = field(default_factory=list)

    def baska_kapsiyor(self, g: date) -> bool:
        return any(a <= g <= b for s in self.baska for a, b in s.araliklar(g))

    def aktif(self, g: date):
        for s in self.sezon:
            for a, b in s.araliklar(g):
                if a <= g <= b:
                    return a, b, s
        return None

    def depoda(self, g: date) -> bool:
        return any(a <= g <= b for s in self.depo for a, b in s.araliklar(g))

    def sonraki(self, g: date):
        aday = [(a, b, s) for s in self.sezon for a, b in s.araliklar(g) if a > g]
        return min(aday, key=lambda x: x[0]) if aday else None

    def onceki(self, g: date):
        aday = [(a, b, s) for s in self.sezon for a, b in s.araliklar(g) if b < g]
        return max(aday, key=lambda x: x[1]) if aday else None


def takvim_yukle(urunler_dizini: Path, bolge: str | None, deniz: str | None, donem_turleri: list[str],
                 yil_boyu_gun: int) -> dict[str, UrunTakvimi]:
    """Bir bölge/deniz için kullanılabilir takvim. Yıl boyu ürün, çiftlik ve yıl boyu satırlar dışarıda kalır."""
    sonuc = {}
    for yol in sorted(Path(urunler_dizini).glob("*.json")):
        u = json.loads(yol.read_text(encoding="utf-8"))
        if u.get("aktif") is False or u.get("yil_boyu") is True or u.get("uretim_sekli") == "ciftlik":
            continue
        t = UrunTakvimi(u["id"], u.get("ad", u["id"]))
        for m in u.get("mevsimler") or []:
            s = Satir(u["id"], m["kapsam_turu"], m["kapsam_id"], m["donem_turu"], m["bas"], m["bit"],
                      m.get("kaynak_adi", ""), m.get("kaynak_link"), m.get("guven", ""))
            if m["kapsam_turu"] == "deniz" and deniz and m["kapsam_id"] != deniz:
                t.baska.append(s)                  # öteki denizler: tanık değil, engel
                continue
            if not ((m["kapsam_turu"] == "bolge" and m["kapsam_id"] == bolge) or
                    (m["kapsam_turu"] == "deniz" and deniz and m["kapsam_id"] == deniz)):
                continue
            if s.donem_turu == "depo":
                t.depo.append(s)
            elif s.donem_turu in donem_turleri and s.uzunluk() < yil_boyu_gun:
                t.sezon.append(s)
            else:
                t.baska.append(s)                  # yıl boyu satır: ürün her gün takvimde
        if t.sezon:
            sonuc[u["id"]] = t
    return sonuc


# --------------------------------------------------------------------------
# Gözlemler
# --------------------------------------------------------------------------
class Gozlemler:
    """Bir (ya da birkaç) kaynağın günlük kayıtları. Pazar günü = boş olmayan ve taşınmamış liste."""

    def __init__(self, kayitlar: list[dict]):
        self.gunler: dict[str, dict] = {}
        for k in sorted(kayitlar, key=lambda x: x["t"]):
            self.gunler[k["t"]] = k
        onceki = None
        self.tasindi: set[str] = set()
        for t, k in sorted(self.gunler.items()):
            if k.get("bos"):
                continue
            if (onceki is not None and k.get("ozet") == onceki) or (k.get("bulten") and k["bulten"] != t):
                self.tasindi.add(t)
            onceki = k.get("ozet")

    def pazar_gunleri(self, bas: date, bit: date) -> list[str]:
        return [t for t, k in sorted(self.gunler.items())
                if bas.isoformat() <= t <= bit.isoformat() and not k.get("bos") and t not in self.tasindi]

    def var_mi(self, t: str, urun_id: str, es: Eslestirme) -> list[str]:
        """O gün ürünü temsil eden sinyal kalemleri (boş liste: yok)."""
        return [a for a in self.gunler[t].get("adlar", []) if (k := es.sinyal_kalemi(a)) and k.urun_id == urun_id]

    def herhangi(self, t: str, urun_id: str, es: Eslestirme) -> bool:
        """O gün ürünün herhangi bir kalemi (sera/ithal/yıl boyu dahil) listede mi? 'Yok' demeden önce bakılır."""
        return any((k := es.bul(a)) and k.urun_id == urun_id for a in self.gunler[t].get("adlar", []))


# --------------------------------------------------------------------------
# Kurallar
# --------------------------------------------------------------------------
@dataclass
class Sinyal:
    kural: str
    urun_id: str
    urun_adi: str
    satir: Satir
    sezon_bas: date
    sezon_bit: date
    bugun: date
    pazar_gunu: int = 0
    gorulen_gun: int = 0
    ilk: str | None = None
    son: str | None = None
    kalemler: list[str] = field(default_factory=list)
    pencere_bas: date | None = None
    diger_satirlar: list = field(default_factory=list)

    @property
    def sezon_yili(self) -> int:
        return self.sezon_bas.year


def degerlendir(gozlem: Gozlemler, es: Eslestirme, takvim: dict[str, UrunTakvimi], bugun: date, ay: dict) -> list[Sinyal]:
    W = ay["pencere_gun"]
    sinyaller: list[Sinyal] = []
    urunler = {k.urun_id for k in es.kalemler.values() if not k.yil_boyu_halde}
    for uid in sorted(urunler & set(takvim)):
        t = takvim[uid]
        pb = bugun - timedelta(days=W - 1)
        pg = gozlem.pazar_gunleri(pb, bugun)
        gorulen = [g for g in pg if gozlem.var_mi(g, uid, es)]
        kalemler = sorted({a for g in gorulen for a in gozlem.var_mi(g, uid, es)})
        aktif = t.aktif(bugun)

        def sinyal(kural, a, b, s, **ek):
            return Sinyal(kural, uid, t.ad, s, a, b, bugun, len(pg), len(gorulen),
                          gorulen[0] if gorulen else None, gorulen[-1] if gorulen else None, kalemler, pb,
                          diger_satirlar=t.baska, **ek)

        if aktif is None:
            if t.depoda(bugun) or t.baska_kapsiyor(bugun) or not pg:
                continue
            bol = len(gorulen) >= ay["erken_en_az_pazar_gunu"] and len(gorulen) / len(pg) >= ay["erken_en_az_oran"]
            if not bol:
                continue
            sonraki, onceki = t.sonraki(bugun), t.onceki(bugun)
            kalan = (sonraki[0] - bugun).days if sonraki else 10 ** 6
            gecen = (bugun - onceki[1]).days if onceki else 10 ** 6
            if gecen <= kalan:
                if ay["bitti_fark_gun"] <= gecen <= ay["bitti_ufuk_gun"]:
                    sinyaller.append(sinyal("uzadi", *onceki))
            elif ay["erken_fark_gun"] <= kalan <= ay["erken_ufuk_gun"]:
                sinyaller.append(sinyal("erken", *sonraki))
            continue

        a, b, s = aktif
        # (b) Sezon başladı ama halde yok
        if (bugun - a).days >= ay["yok_gecikme_gun"]:
            sezon_pg = gozlem.pazar_gunleri(a, bugun)
            pencere_pg = gozlem.pazar_gunleri(max(a, pb), bugun)
            if (len(pencere_pg) >= ay["yok_en_az_pazar_gunu"]
                    and not any(gozlem.herhangi(g, uid, es) for g in sezon_pg)):
                sg = Sinyal("yok", uid, t.ad, s, a, b, bugun, len(sezon_pg), 0, None, None, [], a, diger_satirlar=t.baska)
                sinyaller.append(sg)
                continue
        # (c) Halden çekildi, takvim sürüyor
        if (b - bugun).days >= ay["cekildi_kalan_gun"]:
            sezon_pg = gozlem.pazar_gunleri(a, bugun)
            son_k = sezon_pg[-ay["cekildi_son_pazar_gunu"]:]
            once = sezon_pg[:-ay["cekildi_son_pazar_gunu"]]
            once_gorulen = [g for g in once if gozlem.var_mi(g, uid, es)]
            if (len(son_k) >= ay["cekildi_son_pazar_gunu"]
                    and len(once_gorulen) >= ay["cekildi_once_en_az_pazar_gunu"]
                    and not any(gozlem.herhangi(g, uid, es) for g in son_k)):
                kal = sorted({x for g in once_gorulen for x in gozlem.var_mi(g, uid, es)})
                sinyaller.append(Sinyal("cekildi", uid, t.ad, s, a, b, bugun, len(son_k), len(once_gorulen),
                                        once_gorulen[0], once_gorulen[-1], kal, a, diger_satirlar=t.baska))
    return sinyaller


def hks_egilimi(hks_kayitlari: list[dict], es: Eslestirme, urun_id: str, gun: int, oran: float) -> dict | None:
    """HKS ilk sayfasında ürün varsa son 'gun' kayıt ile önceki 'gun' kaydın toplam işlem hacmi karşılaştırması."""
    seri = []
    for k in sorted(hks_kayitlari, key=lambda x: x["t"]):
        toplam = sum(v for ad, v in (k.get("hacim") or {}).items() if (kk := es.bul(ad)) and kk.urun_id == urun_id)
        if (k.get("hacim") or {}) and any((kk := es.bul(ad)) and kk.urun_id == urun_id for ad in k["hacim"]):
            seri.append((k["t"], toplam))
    if len(seri) < 2 * gun:
        return {"yeterli": False, "gun": len(seri)} if seri else None
    once = sum(v for _, v in seri[-2 * gun:-gun])
    son = sum(v for _, v in seri[-gun:])
    if once <= 0:
        return {"yeterli": False, "gun": len(seri)}
    d = (son - once) / once
    yon = "artiyor" if d >= oran else ("azaliyor" if d <= -oran else "duz")
    return {"yeterli": True, "yon": yon, "degisim": round(d * 100), "bas": seri[-2 * gun][0], "bit": seri[-1][0]}
