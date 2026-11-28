"""Mevsim toplayıcısı (Aşama 3): her sabah güvenilir kaynakları tarar, bu yılın işaretlerini
ÖNERİYE çevirir (Pull Request / Issue). Hiçbir şeyi kendisi yayınlamaz, hiçbir şeyi birleştirmez.

Kullanım (depo kökünden):
  python toplayici/toplayici.py --kuru                 # kuru çalıştırma: okur, raporlar; öneri açmaz, dosya yazmaz
  python toplayici/toplayici.py --kaynak izmir_balik   # tek kaynak
  python toplayici/toplayici.py --gosterim             # örnek veriyle bir öneriyi baştan sona göster (kuru)
  python toplayici/toplayici.py --durum-dizini _durum/durum   # Actions: durum dalının klasörü
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BURASI = Path(__file__).resolve().parent
KOK = BURASI.parent
sys.path.insert(0, str(BURASI))
sys.path.insert(0, str(KOK / "araclar"))

import kaynaklar as K  # noqa: E402
import kurallar as R   # noqa: E402

KAYNAK_SIRASI = ["izmir_sebze_meyve", "izmir_balik", "hks", "konya", "resmi_gazete"]
IZMIR_ATIF = ("İzmir Büyükşehir Belediyesi Açık Veri Portalı (acikveri.bizizmir.com), CC BY 4.0 lisansıyla.")
KAYNAK_BILGI = {
    "izmir_sebze_meyve": {
        "not_adi": "İzmir Büyükşehir Belediyesi Açık Veri Portalı, sebze ve meyve hal bülteni (CC BY 4.0)",
        "link": "https://acikveri.bizizmir.com/dataset/sebze-ve-meyve-hal-fiyatlari",
        "hal": "İzmir halinde", "kisa": "İzmir hali (sebze-meyve)"},
    "izmir_balik": {
        "not_adi": "İzmir Büyükşehir Belediyesi Açık Veri Portalı, balık hal bülteni (CC BY 4.0)",
        "link": "https://acikveri.bizizmir.com/dataset/balik-hal-fiyatlari",
        "hal": "İzmir balık halinde", "kisa": "İzmir balık hali"},
    "konya": {
        "not_adi": "Konya Büyükşehir Belediyesi meyve-sebze hali listesi",
        "link": "https://www.konya.bel.tr/hal-fiyatlari",
        "hal": "Konya halinde", "kisa": "Konya hali"},
}
BOT = ["-c", "user.name=github-actions[bot]",
       "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com"]


def simdi() -> str:
    return datetime.now(timezone(timedelta(hours=3))).replace(microsecond=0).isoformat()


def json_oku(yol: Path, varsayilan):
    try:
        return json.loads(Path(yol).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return varsayilan


def json_yaz(yol: Path, veri) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(json.dumps(veri, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Gözlem deposu: durum/gozlem/<yıl>.jsonl (gün başına kaynak başına tek satır)
# --------------------------------------------------------------------------
class Depo:
    def __init__(self, dizin: Path):
        self.dizin = Path(dizin)
        self.kayitlar: list[dict] = []
        self.yeni: list[dict] = []
        for yol in sorted((self.dizin / "gozlem").glob("*.jsonl")):
            for satir in yol.read_text(encoding="utf-8").splitlines():
                if satir.strip():
                    try:
                        self.kayitlar.append(json.loads(satir))
                    except ValueError:
                        pass

    def kaynak(self, k: str) -> list[dict]:
        return [x for x in self.kayitlar if x.get("k") == k]

    def var(self, k: str, t: str) -> bool:
        return any(x.get("k") == k and x.get("t") == t for x in self.kayitlar)

    def ekle(self, kayit: dict) -> None:
        self.kayitlar = [x for x in self.kayitlar if not (x.get("k") == kayit["k"] and x.get("t") == kayit["t"])]
        self.kayitlar.append(kayit)
        self.yeni.append(kayit)

    def yaz(self) -> None:
        yillar = {}
        for x in sorted(self.kayitlar, key=lambda x: (x["t"], x["k"])):
            yillar.setdefault(x["t"][:4], []).append(json.dumps(x, ensure_ascii=False, separators=(",", ":")))
        for y, satirlar in yillar.items():
            yol = self.dizin / "gozlem" / f"{y}.jsonl"
            yol.parent.mkdir(parents=True, exist_ok=True)
            yol.write_text("\n".join(satirlar) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Kaynakları okuma — her biri kendi try/except'inde
# --------------------------------------------------------------------------
def kaynak_oku(ad: str, ayar: dict, depo: Depo, bugun: date, indir, rapor: dict) -> list[dict]:
    """Kaynağı okur, yeni gözlemleri depoya ekler. Resmî Gazete için eşleşen başlıkları döndürür."""
    ia = ayar["istek"]
    istekler = rapor["istekler"]

    def getir(url):
        if istekler:
            time.sleep(ia["istekler_arasi_bekleme_sn"])
        y = indir(url, ia)
        istekler.append({"url": url, "http": y.http, "bayt": len(y.govde)})
        return y

    if ad in ("izmir_sebze_meyve", "izmir_balik"):
        for i in range(ia["geri_bakis_gun"]):
            g = bugun - timedelta(days=i)
            t = g.isoformat()
            if depo.var(ad, t):
                continue
            y = getir(K.IZMIR_URL[ad].format(tarih=t))
            gz = K.izmir_ayristir(ad, t, y.http, y.govde)
            istekler[-1]["satir"] = len(gz.adlar)
            if gz.bos and g == bugun:
                continue                       # bugünün bülteni sonra çıkabilir; yarın yeniden bakılır
            depo.ekle(gz.kayit())
        return []
    if ad == "konya":
        y = getir(K.KONYA_URL)
        gz = K.konya_ayristir(y.http, y.govde)
        istekler[-1]["satir"] = len(gz.adlar)
        istekler[-1]["liste_tarihi"] = gz.tarih
        if not depo.var(ad, gz.tarih):
            depo.ekle(gz.kayit())
        return []
    if ad == "hks":
        y = getir(K.HKS_URL)
        gz = K.hks_ayristir(y.http, y.govde)
        istekler[-1]["satir"] = len(gz.adlar)
        istekler[-1]["veri_tarihi"] = gz.tarih
        if not depo.var(ad, gz.tarih):
            depo.ekle(gz.kayit())
        return []
    if ad == "resmi_gazete":
        rg = ayar["resmi_gazete"]
        bulunan = []
        for i in range(rg["geri_bakis_gun"]):
            g = bugun - timedelta(days=i)
            if depo.var(ad, g.isoformat()):
                continue
            y = getir(K.rg_url(g))
            basliklar = K.rg_ayristir(g, y.http, y.govde)
            istekler[-1]["satir"] = len(basliklar)
            es = K.rg_eslesenler(basliklar, rg["anahtar_kaliplar"])
            depo.ekle({"k": ad, "t": g.isoformat(), "baslik_sayisi": len(basliklar), "eslesen": es})
            if es:
                bulunan.append({"tarih": g.isoformat(), "url": K.rg_url(g), "eslesen": es})
        return bulunan
    raise K.KaynakHatasi(f"bilinmeyen kaynak: {ad}")


# --------------------------------------------------------------------------
# Öneri üretimi
# --------------------------------------------------------------------------
def _bolge_ifadesi(s: R.Satir) -> str:
    if s.kapsam_turu == "deniz":
        return {"ege": "Ege Denizi'ndeki", "marmara": "Marmara Denizi'ndeki", "karadeniz": "Karadeniz'deki",
                "akdeniz": "Akdeniz'deki"}.get(s.kapsam_id, s.kapsam_id)
    return {"ege": "Ege'deki", "ic_anadolu": "İç Anadolu'daki"}.get(s.kapsam_id, s.kapsam_id)


def kucuk(metin: str) -> str:
    return metin.replace("I", "ı").replace("İ", "i").lower()


def oneri_kimligi(s: R.Sinyal) -> str:
    return f"{s.urun_id}_{s.kural}_{s.satir.kapsam_id}_{s.sezon_yili}"


def not_olustur(s: R.Sinyal, kaynak: str, ay: dict) -> dict:
    """kaynak/notlar/<yıl>/<id>.json içeriği (yil_notu alanları). Metin fiyattan söz etmez."""
    b = KAYNAK_BILGI[kaynak]
    ad, hal, yer = s.urun_adi, b["hal"], _bolge_ifadesi(s.satir)
    donem = R.DONEM_ADI[s.satir.donem_turu]
    enfazla = s.bugun + timedelta(days=ay["not_gecerlilik_en_fazla_gun"])
    balik = s.satir.kapsam_turu == "deniz"
    hicbir = ("takvimde hiçbir denizde av dönemi görünmediği hâlde" if s.satir.donem_turu == "av"
              else "takvimde hiçbir denizde sezonu görünmediği hâlde")
    ote_deniz = " İzmir balık haline başka denizlerden de balık gelir; hal listesi balığın hangi denizden geldiğini ayırmaz."
    if s.kural == "erken" and balik:
        baslik = f"{ad} {hal} takvimden erken görüldü"
        metin = (f"{ad}, {hicbir} {R.tr_gun_ay(date.fromisoformat(s.ilk))} tarihinden bu yana {hal} {s.gorulen_gun} "
                 f"pazar gününde listelendi. Takvimde {yer} {donem} {R.tr_gun_ay(s.sezon_bas)} tarihinde başlıyor. "
                 f"Bu, sezonun erken başladığını göstermez: balık başka bir av yönteminden, depodan ya da yurt dışından "
                 f"gelmiş olabilir.")
        bit = min(s.sezon_bas - timedelta(days=1), enfazla)
    elif s.kural == "uzadi" and balik:
        baslik = f"{ad} takvim bittikten sonra da {hal}"
        metin = (f"Takvimde {yer} {donem} {R.tr_gun_ay(s.sezon_bit)} tarihinde bitti; {hicbir} {kucuk(ad)} son "
                 f"{(s.bugun - s.pencere_bas).days + 1} günde {s.gorulen_gun} pazar gününde {hal} listelendi. "
                 f"Bu, sezonun uzadığını göstermez: balık başka bir av yönteminden, depodan ya da yurt dışından gelmiş olabilir.")
        bit = enfazla
    elif s.kural == "erken":
        baslik = f"{ad} {hal} takvimden erken görüldü"
        metin = (f"{ad}, {R.tr_gun_ay(date.fromisoformat(s.ilk))} tarihinden bu yana {hal} {s.gorulen_gun} pazar gününde "
                 f"listelendi. Takvimde {yer} {donem} {R.tr_gun_ay(s.sezon_bas)} tarihinde başlıyor. Bu, sezonun erken "
                 f"başladığını göstermez: ürün seradan, başka bölgeden, depodan ya da yurt dışından gelmiş olabilir.")
        bit = min(s.sezon_bas - timedelta(days=1), enfazla)
    elif s.kural == "uzadi":
        baslik = f"{ad} takvim bittikten sonra da {hal}"
        metin = (f"Takvimde {yer} {donem} {R.tr_gun_ay(s.sezon_bit)} tarihinde bitti, ama {kucuk(ad)} son "
                 f"{(s.bugun - s.pencere_bas).days + 1} günde {s.gorulen_gun} pazar gününde {hal} listelendi. "
                 f"Bu, sezonun uzadığını göstermez: ürün depodan, seradan ya da başka bölgeden gelmiş olabilir.")
        bit = enfazla
    elif s.kural == "yok":
        baslik = f"{ad} bu yıl {hal} henüz görünmedi"
        metin = (f"Takvimde {yer} {donem} {R.tr_gun_ay(s.sezon_bas)} tarihinde başladı, ama {kucuk(ad)} o günden bu yana "
                 f"({s.pazar_gunu} pazar günü) {hal} listelenmedi. Bu, sezonun geciktiğini kesin göstermez: ürün semt "
                 f"pazarına halden geçmeden gelebilir ya da hal listesine yazılmamış olabilir." + (ote_deniz if balik else ""))
        bit = min(s.sezon_bit, enfazla)
    else:  # cekildi
        baslik = f"{ad} {hal.replace('halinde', 'halinden')} çekildi"
        metin = (f"{ad}, {R.tr_gun_ay(date.fromisoformat(s.son))} tarihinden sonra {hal} listelenmiyor (son "
                 f"{s.pazar_gunu} pazar günü); takvimde {yer} {donem} {R.tr_gun_ay(s.sezon_bit)} tarihine kadar sürüyor. "
                 f"Bu, sezonun erken bittiğini kesin göstermez." + (ote_deniz if balik else ""))
        bit = min(s.sezon_bit, enfazla)
    if bit < s.bugun:
        bit = s.bugun
    return {
        "id": oneri_kimligi(s), "urun_id": s.urun_id,
        "kapsam_turu": s.satir.kapsam_turu, "kapsam_id": s.satir.kapsam_id,
        "sinyal_turu": "hal", "baslik": baslik, "metin": metin,
        "gecerlilik_bas": s.bugun.isoformat(), "gecerlilik_bit": bit.isoformat(),
        "kaynak_adi": b["not_adi"], "kaynak_link": b["link"],
        "onay_tarihi": s.bugun.isoformat(), "bildirimde_goster": False,
    }


KURAL_ADI = {"erken": "Halde göründü, takvimden erken", "yok": "Sezon başladı ama halde yok",
             "cekildi": "Halden çekildi, takvim sürüyor", "uzadi": "Takvim bitti ama halde bol"}
TANIK_UYUMU = {"erken": {"artiyor"}, "uzadi": {"artiyor", "duz"}, "yok": {"azaliyor"}, "cekildi": {"azaliyor"}}


def pr_govdesi(s: R.Sinyal, kaynak: str, nt: dict, yol: str, tanik: list[str], kontrol: str) -> str:
    b = KAYNAK_BILGI[kaynak]
    st = s.satir
    gozlem = []
    if s.kural in ("erken", "uzadi"):
        gozlem.append(f"- {R.tr_tarih(s.pencere_bas)} – {R.tr_tarih(s.bugun)} arasında halin liste yayımladığı "
                      f"**{s.pazar_gunu} pazar gününün {s.gorulen_gun}'ünde** ürün listelendi "
                      f"(ilk: {R.tr_tarih(date.fromisoformat(s.ilk))}, son: {R.tr_tarih(date.fromisoformat(s.son))}).")
    elif s.kural == "yok":
        gozlem.append(f"- Sezonun başladığı {R.tr_tarih(s.sezon_bas)} gününden {R.tr_tarih(s.bugun)} gününe kadar halin "
                      f"liste yayımladığı **{s.pazar_gunu} pazar gününün hiçbirinde** ürün listelenmedi "
                      f"(sera, ithal ya da yıl boyu satılan kalemler dahil hiçbir adla).")
    else:
        gozlem.append(f"- Bu sezon {s.gorulen_gun} pazar gününde listelendi (ilk: {R.tr_tarih(date.fromisoformat(s.ilk))}, "
                      f"son: {R.tr_tarih(date.fromisoformat(s.son))}); **son {s.pazar_gunu} pazar gününde hiç listelenmedi**.")
    if s.kalemler:
        gozlem.append("- Sayılan hal kalemleri: " + ", ".join(f"`{k}`" for k in s.kalemler))
    gozlem.append("- Hafta sonu ve bayramda boş gelen listeler ile bir önceki günün birebir aynısı olan (taşınmış) "
                  "listeler sayılmadı. Sera, ithal, kültür ve donuk kalemler ile yılın neredeyse her günü listelenen "
                  "kalemler 'erken' ve 'uzadı' kurallarında sayılmaz.")
    return "\n".join([
        f"**Kural:** {KURAL_ADI[s.kural]} · **Kaynak:** {b['kisa']} · "
        f"**Öneri kimliği:** `{nt['id']}`",
        "",
        "## Ne görüldü",
        *gozlem,
        "",
        "## Takvimde ne yazıyor",
        f"- {_bolge_ifadesi(st)} {R.DONEM_ADI[st.donem_turu]}: **{R.tr_gun_ay(s.sezon_bas)} – {R.tr_gun_ay(s.sezon_bit)}** "
        f"(güven: {st.guven}; kaynak: {st.kaynak_adi}" + (f", {st.kaynak_link}" if st.kaynak_link else "") + ")",
        *([f"- Öteki denizler ve yıl boyu kayıtlar: " + "; ".join(
            f"{_bolge_ifadesi(x)} {R.DONEM_ADI[x.donem_turu]} {x.bas} – {x.bit}" for x in s.diger_satirlar)]
          if s.diger_satirlar else []),
        *(["- İzmir balık hali her denizden balık satar ve listesi denizi ayırmaz; bu yüzden 'erken' ve 'uzadı' "
           "kuralları yalnızca balık takvimde **hiçbir denizde** sezonda değilken çalışır."] if st.kapsam_turu == "deniz" else []),
        "- Toplayıcı bu takvimi **değiştirmez**; bu PR yalnızca bir \"bu yılın notu\" ekler.",
        "",
        "## Bu neden yalnızca bir öneri?",
        "Hal bir toptan piyasadır. Bir ürünün halde erken görünmesi ya da görünmemesi sezonun kaydığını kanıtlamaz: "
        "ürün seradan, başka bölgeden, depodan ya da yurt dışından gelebilir; semt pazarına halden geçmeden de ulaşabilir. "
        "Bu yüzden not metni yalnızca görüleni anlatır.",
        "",
        "## İkinci tanık",
        *(tanik or ["- Yok (ikinci kaynakta bu ürün için yeterli veri yok)."]),
        "",
        "## Eklenen dosya",
        f"`{yol}` — uygulamada ürün kartında \"Bu yılın notu\" olarak görünür; **bildirim göndermez** "
        "(`bildirimde_goster: false`).",
        "```json", json.dumps(nt, ensure_ascii=False, indent=1), "```",
        "",
        "## Kaynaklar",
        f"- {b['not_adi']}: {b['link']}",
        *([f"- Atıf: {IZMIR_ATIF}"] if kaynak.startswith("izmir") else []),
        "",
        "## Ne yapmalısın?",
        "- **Uygun buluyorsan:** \"Merge pull request\" düğmesine bas. Not birkaç dakika içinde uygulamaya gider.",
        "- **Uygun değilse:** \"Close pull request\" düğmesine bas. Aynı öneri bu sezon yeniden açılmaz.",
        "- **Hiçbir şey yapmazsan:** öneri bekler; uygulamaya hiçbir şey gitmez.",
        "- Metni değiştirmek istersen dosyayı bu PR içinde düzenleyebilirsin (\"Files changed\" → kalem simgesi).",
        "",
        "## Otomatik kontrol",
        kontrol,
        "",
        "_Bu PR, toplayıcı tarafından kurallara göre açıldı (yapay zekâ kullanılmadı). Birleştirme her zaman insan kararıdır._",
    ])


def tanik_satirlari(s: R.Sinyal, depo: Depo, esler: dict, ayar: dict, kaynak: str) -> list[str]:
    satirlar = []
    if "hks" in esler:
        h = ayar["kurallar"]["hks"]
        e = R.hks_egilimi(depo.kaynak("hks"), esler["hks"], s.urun_id, h["egilim_gun"], h["degisim_orani"])
        if e and e.get("yeterli"):
            yon = {"artiyor": "artıyor", "azaliyor": "azalıyor", "duz": "belirgin değişmiyor"}[e["yon"]]
            uyum = "bu öneriyi **destekliyor**" if e["yon"] in TANIK_UYUMU[s.kural] else "bu öneriyi desteklemiyor"
            satirlar.append(f"- Hal Kayıt Sistemi (Türkiye geneli, ilk sayfa): işlem hacmi son {h['egilim_gun']} kayıtta önceki "
                            f"{h['egilim_gun']} kayda göre {yon} (%{e['degisim']:+d}); {uyum}.")
        elif e:
            satirlar.append(f"- Hal Kayıt Sistemi: ürün ilk sayfada var ama eğilim için yeterli gün yok ({e['gun']} gün).")
    if kaynak.startswith("izmir") and "konya" in esler:
        kg = R.Gozlemler(depo.kaynak("konya"))
        son = kg.pazar_gunleri(s.bugun - timedelta(days=13), s.bugun)
        if son:
            var = [g for g in son if kg.herhangi(g, s.urun_id, esler["konya"])]
            satirlar.append(f"- Konya hali (İç Anadolu, bilgi için): son 14 günün {len(son)} listesinin {len(var)}'inde ürün var.")
    return satirlar


def derle_kontrol(kaynak_dizini: Path) -> tuple[bool, str]:
    """derle.py ile şema + iş kuralı doğrulaması (PR kontrolünün aynısı)."""
    import derle
    veri, hatalar, uyarilar = derle.derle(kaynak_dizini, KOK / "sema" / "v1.schema.json", 1, None)
    for n in veri.get("yil_notlari", []):
        for alan in ("kaynak_adi",):                 # baslik/metin derle.py'nin kendisinde denetlenir
            if derle._fiyat_dili(n.get(alan)):
                hatalar.append(f"yil_notlari/{n.get('id')}: {alan} fiyattan söz ediyor")
    if hatalar:
        return False, "Doğrulama **başarısız**:\n" + "\n".join(f"- {h}" for h in hatalar[:20])
    return True, (f"Toplayıcı PR'ı açmadan önce `derle.py` doğrulamasını çalıştırdı: **geçti** "
                  f"({len(veri['urunler'])} ürün, {len(veri['yil_notlari'])} yıl notu). PR kontrolü de ayrıca başlatıldı.")


# --------------------------------------------------------------------------
# GitHub işlemleri (gh CLI + git). Kuru çalıştırmada hiçbiri yapılmaz.
# --------------------------------------------------------------------------
class GitHub:
    def __init__(self, kok: Path):
        self.kok = kok

    def _calis(self, *komut, cwd=None, girdi=None) -> str:
        r = subprocess.run(list(komut), cwd=cwd or self.kok, capture_output=True, text=True, input=girdi,
                           encoding="utf-8", timeout=180)
        if r.returncode != 0:
            raise RuntimeError(f"{' '.join(komut[:3])}: {r.stderr.strip()[:300]}")
        return r.stdout

    def onceden_var_mi(self, kimlik: str) -> bool:
        pr = self._calis("gh", "pr", "list", "--state", "all", "--head", f"oneri/{kimlik}", "--json", "number")
        if json.loads(pr or "[]"):
            return True
        iss = self._calis("gh", "issue", "list", "--state", "all", "--search", f"{kimlik} in:title", "--json", "number,title")
        return any(kimlik in i["title"] for i in json.loads(iss or "[]"))

    def pr_ac(self, kimlik: str, dosya_yolu: str, icerik: dict, baslik: str, govde_uret) -> int:
        dal = f"oneri/{kimlik}"
        self._calis("git", "fetch", "--quiet", "origin", "main")
        gecici = Path(tempfile.mkdtemp(prefix="oneri_"))
        agac = gecici / "agac"
        try:
            self._calis("git", "worktree", "add", "--quiet", "-B", dal, str(agac), "FETCH_HEAD")
            hedef = agac / dosya_yolu
            if hedef.exists():
                raise RuntimeError("not dosyası main'de zaten var")
            json_yaz(hedef, icerik)
            ok, kontrol = derle_kontrol(agac / "kaynak")
            if not ok:
                raise RuntimeError(kontrol)
            self._calis("git", *BOT, "add", dosya_yolu, cwd=agac)
            self._calis("git", *BOT, "commit", "--quiet", "-m", f"Öneri: {baslik}\n\nToplayıcı kuralı, kimlik {kimlik}.", cwd=agac)
            self._calis("git", "push", "--quiet", "origin", f"{dal}:{dal}", cwd=agac)
            govde = gecici / "govde.md"
            govde.write_text(govde_uret(kontrol), encoding="utf-8")
            url = self._calis("gh", "pr", "create", "--base", "main", "--head", dal, "--title", f"Öneri: {baslik} [{kimlik}]",
                              "--body-file", str(govde)).strip()
            try:
                self._calis("gh", "workflow", "run", "pr_kontrol.yml", "--ref", dal)
            except RuntimeError:
                pass
            return int(url.rstrip("/").split("/")[-1])
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(agac)], cwd=self.kok, capture_output=True)
            shutil.rmtree(gecici, ignore_errors=True)

    def issue_ac(self, baslik: str, govde: str) -> int:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(govde)
        try:
            url = self._calis("gh", "issue", "create", "--title", baslik, "--body-file", f.name).strip()
        finally:
            os.unlink(f.name)
        return int(url.rstrip("/").split("/")[-1])


def rg_issue(b: dict) -> tuple[str, str, str]:
    g = date.fromisoformat(b["tarih"])
    kimlik = f"rg_{g:%Y%m%d}"
    baslik = f"Av kuralı değişmiş olabilir — takvimi gözden geçir (Resmî Gazete {g:%d.%m.%Y}) [{kimlik}]"
    satirlar = [f"Resmî Gazete'nin {R.tr_tarih(g)} tarihli sayısının fihristinde su ürünleri avcılığıyla ilgili olabilecek "
                f"başlık(lar) görüldü:", ""]
    satirlar += [f"- [{e['baslik']}]({e['link']})" for e in b["eslesen"]]
    satirlar += ["", f"Fihrist: {b['url']}", "",
                 "## Bu ne demek?",
                 "Toplayıcı yalnızca başlıktaki kelimelere bakar; metni yorumlamaz. Değişiklik hangi balığın hangi tarihini "
                 "etkiliyor, bunu bir insanın okuması gerekir. Takvim kendiliğinden değişmez.",
                 "", "## Ne yapmalısın?",
                 "- Metni oku (ya da Claude'dan okumasını iste). Av yasağı / av dönemi tarihi değiştiyse takvim düzeltmesi "
                 "ayrı bir Pull Request ile önerilir.",
                 "- İlgisizse (ör. yalnızca su ürünleri ithalatı) bu kaydı \"Close issue\" ile kapat.",
                 "", "_Bu kayıt toplayıcı tarafından kurallara göre açıldı (yapay zekâ kullanılmadı)._"]
    return kimlik, baslik, "\n".join(satirlar)


# --------------------------------------------------------------------------
# Ana akış
# --------------------------------------------------------------------------
def calistir(durum_dizini: Path, kuru: bool, tek_kaynak: str | None, bugun: date, indir=K.indir,
             github: GitHub | None = None, ayar_yolu: Path = BURASI / "ayarlar.json",
             urunler_dizini: Path = KOK / "kaynak" / "urunler", cikti=print, en_fazla: int | None = None) -> dict:
    ayar = json.loads(Path(ayar_yolu).read_text(encoding="utf-8"))
    depo = Depo(durum_dizini)
    onceki = json_oku(durum_dizini / "son_calisma.json", {})
    oneriler = json_oku(durum_dizini / "oneriler.json", {})
    bekleyen = json_oku(durum_dizini / "bekleyen.json", {})
    esler = R.eslestirme_yukle(BURASI / "eslestirme.json", ayar)
    rapor = {"calisma_zamani": simdi(), "bugun": bugun.isoformat(), "kuru": kuru, "kaynaklar": {},
             "eslesmeyen_adlar": {}, "oneriler": {"acilan": [], "zaten_var": [], "kuru_gosterilen": [], "ertelendi": [], "suresi_doldu": [], "hata": []}}
    sinir = en_fazla if en_fazla is not None else ayar.get("gunluk_en_fazla_oneri", 3)
    rg_bulunan = []

    for ad in KAYNAK_SIRASI:
        ka = ayar["kaynaklar"][ad]
        eski = (onceki.get("kaynaklar") or {}).get(ad, {})
        r = {"ad": ka["ad"], "durum": None, "istekler": [], "hata": None,
             "ardisik_hata": eski.get("ardisik_hata", 0), "son_basarili": eski.get("son_basarili")}
        rapor["kaynaklar"][ad] = r
        if not ka.get("acik", True):
            r["durum"] = "kapali"
            continue
        if tek_kaynak and tek_kaynak != ad:
            r["durum"] = "atlandi"
            continue
        try:
            rg_bulunan += kaynak_oku(ad, ayar, depo, bugun, indir, r)
            r["durum"] = "basarili"
            r["ardisik_hata"] = 0
            r["son_basarili"] = rapor["calisma_zamani"]
        except Exception as e:                       # bir kaynak çökse de diğerleri devam eder
            r["durum"] = "hata"
            r["hata"] = f"{type(e).__name__}: {e}"[:300]
            r["ardisik_hata"] = r["ardisik_hata"] + 1
            cikti(f"[{ad}] HATA: {r['hata']}")
        if ad in esler and r["durum"] == "basarili":
            adlar = {a for x in depo.yeni if x["k"] == ad for a in x.get("adlar", [])}
            r["eslesmeyen"] = esler[ad].eslesmeyenler(adlar)
            if r["eslesmeyen"]:
                rapor["eslesmeyen_adlar"][ad] = r["eslesmeyen"]

    # Sinyaller
    adaylar = []
    try:
        for kaynak, kural_adi in (("izmir_sebze_meyve", "izmir"), ("izmir_balik", "izmir"), ("konya", "konya")):
            ay = ayar["kurallar"][kural_adi]
            if not ayar["kaynaklar"][kaynak].get("acik", True):
                continue
            takvim = R.takvim_yukle(urunler_dizini, ay["bolge"], ay["deniz"], ay["donem_turleri"], ayar["yil_boyu_takvim_gun"])
            for s in R.degerlendir(R.Gozlemler(depo.kaynak(kaynak)), esler[kaynak], takvim, bugun, ay):
                adaylar.append((kaynak, ay, s))
    except Exception as e:
        rapor["oneriler"]["hata"].append(f"kurallar: {type(e).__name__}: {e}")
        cikti(traceback.format_exc())

    # Bugünün adayları + önceki günlerden sıraya alınmış (ertelenmiş) öneriler.
    # Sıradakiler önce açılır; geçerlilik süresi dolan sıradan düşer (raporda yazar).
    KONTROL = "@@KONTROL@@"
    sira = []
    for b in bekleyen.values():
        if b["not"]["gecerlilik_bit"] < bugun.isoformat():
            rapor["oneriler"]["suresi_doldu"].append(b["not"]["id"])
        else:
            sira.append(b)
    sira_kimlik = {b["not"]["id"] for b in sira}
    for kaynak, ay, s in adaylar:
        nt = not_olustur(s, kaynak, ay)
        if nt["id"] in sira_kimlik:
            continue
        sira.append({"not": nt, "yol": f"kaynak/notlar/{s.sezon_yili}/{nt['id']}.json", "kural": s.kural,
                     "urun_id": s.urun_id, "ilk_gorulme": bugun.isoformat(),
                     "govde": pr_govdesi(s, kaynak, nt, f"kaynak/notlar/{s.sezon_yili}/{nt['id']}.json",
                                         tanik_satirlari(s, depo, esler, ayar, kaynak), KONTROL)})
    kalan = {}
    for b in sira:
        nt, yol = b["not"], b["yol"]
        kimlik, baslik = nt["id"], nt["baslik"]
        if kimlik in oneriler or (KOK / yol).exists():
            rapor["oneriler"]["zaten_var"].append(kimlik)
            continue
        if len(rapor["oneriler"]["acilan"]) + len(rapor["oneriler"]["kuru_gosterilen"]) >= sinir:
            rapor["oneriler"]["ertelendi"].append(kimlik)     # günde en fazla N öneri; kalanlar sırada bekler
            kalan[kimlik] = b
            continue
        if kuru or github is None:
            metin = b["govde"].replace(KONTROL, "(kuru çalıştırma: doğrulama PR açılırken yapılır)")
            cikti(f"\n=== KURU: açılacak PR ===\nBaşlık: Öneri: {baslik} [{kimlik}]\nDosya: {yol}\n"
                  f"--- PR metni ---\n{metin}\n=== son ===")
            rapor["oneriler"]["kuru_gosterilen"].append(kimlik)
            continue
        try:
            if github.onceden_var_mi(kimlik):
                oneriler[kimlik] = {"tur": "pr", "no": None, "tarih": bugun.isoformat(), "not": "GitHub'da önceden vardı"}
                rapor["oneriler"]["zaten_var"].append(kimlik)
                continue
            no = github.pr_ac(kimlik, yol, nt, baslik, lambda k, g=b["govde"]: g.replace(KONTROL, k))
            oneriler[kimlik] = {"tur": "pr", "no": no, "tarih": bugun.isoformat(), "kural": b["kural"], "urun_id": b["urun_id"]}
            rapor["oneriler"]["acilan"].append({"id": kimlik, "pr": no})
        except Exception as e:
            rapor["oneriler"]["hata"].append(f"{kimlik}: {e}"[:400])
            kalan[kimlik] = b                                  # açılamadıysa yarın yeniden denenir

    for b in rg_bulunan:
        kimlik, baslik, govde = rg_issue(b)
        if kimlik in oneriler:
            rapor["oneriler"]["zaten_var"].append(kimlik)
            continue
        if kuru or github is None:
            cikti(f"\n=== KURU: açılacak Issue ===\n{baslik}\n{govde}\n=== son ===")
            rapor["oneriler"]["kuru_gosterilen"].append(kimlik)
            continue
        try:
            if github.onceden_var_mi(kimlik):
                oneriler[kimlik] = {"tur": "issue", "no": None, "tarih": bugun.isoformat()}
                continue
            no = github.issue_ac(baslik, govde)
            oneriler[kimlik] = {"tur": "issue", "no": no, "tarih": bugun.isoformat()}
            rapor["oneriler"]["acilan"].append({"id": kimlik, "issue": no})
        except Exception as e:
            rapor["oneriler"]["hata"].append(f"{kimlik}: {e}"[:400])

    rapor["son_basarili_calisma"] = rapor["calisma_zamani"]
    rapor["onceki_basarili_calisma"] = onceki.get("son_basarili_calisma")
    md = durum_md(rapor)
    if not kuru:
        depo.yaz()
        json_yaz(durum_dizini / "oneriler.json", oneriler)
        json_yaz(durum_dizini / "bekleyen.json", kalan)
        json_yaz(durum_dizini / "son_calisma.json", rapor)
        (durum_dizini / "DURUM.md").write_text(md, encoding="utf-8")
    cikti(md)
    ozet = os.environ.get("GITHUB_STEP_SUMMARY")
    if ozet:
        with open(ozet, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    return rapor


DURUM_ADI = {"basarili": "✅ okundu", "hata": "❌ okunamadı", "kapali": "⏸ kapalı (ayarlar.json)", "atlandi": "– bu çalıştırmada atlandı"}


def durum_md(r: dict) -> str:
    s = ["# Toplayıcı durumu", "",
         f"Son çalışma: **{r['calisma_zamani']}** (Türkiye saati)" + (" — **kuru çalıştırma** (hiçbir şey kaydedilmedi)" if r["kuru"] else ""),
         "", "| Kaynak | Durum | İstekler (HTTP, satır) | Üst üste hata |", "|---|---|---|---|"]
    for k, v in r["kaynaklar"].items():
        ist = "; ".join(f"{x.get('http')}, {x.get('satir', '-')}" for x in v["istekler"]) or "-"
        hata = f" — {v['hata']}" if v.get("hata") else ""
        s.append(f"| {v['ad']} | {DURUM_ADI.get(v['durum'], v['durum'])}{hata} | {ist} | {v['ardisik_hata']} |")
    o = r["oneriler"]
    s += ["", "## Öneriler",
          f"- Yeni açılan: {', '.join(str(x.get('pr') or x.get('issue')) + ' (' + x['id'] + ')' for x in o['acilan']) or 'yok'}",
          f"- Daha önce açılmış (yeniden açılmadı): {len(o['zaten_var'])}"]
    if o["kuru_gosterilen"]:
        s.append(f"- Kuru çalıştırmada gösterilen: {', '.join(o['kuru_gosterilen'])}")
    if o["ertelendi"]:
        s.append(f"- Günlük sınır nedeniyle sırada bekleyen (sonraki günlerde açılır): {', '.join(o['ertelendi'])}")
    if o.get("suresi_doldu"):
        s.append(f"- Sırada beklerken geçerlilik süresi dolan (açılmadı): {', '.join(o['suresi_doldu'])}")
    if o["hata"]:
        s.append("- Açılamayan: " + "; ".join(o["hata"]))
    if not o["acilan"] and not o["kuru_gosterilen"]:
        s.append("- Bugün yeni bir işaret yok. Bu normaldir.")
    if r["eslesmeyen_adlar"]:
        s += ["", "## Eşleşmeyen hal adları (hata değil; `toplayici/eslestirme.json`'a eklenebilir)"]
        for k, v in r["eslesmeyen_adlar"].items():
            s.append(f"- {k}: " + ", ".join(f"`{a}`" for a in v))
    s += ["", f"Kaynak atfı: {IZMIR_ATIF}"]
    return "\n".join(s) + "\n"


def gosterim(cikti=print) -> dict:
    """Örnek gözlemlerle (toplayici/ornekler/gosterim) uçtan uca bir öneriyi kuru olarak gösterir."""
    dizin = BURASI / "ornekler" / "gosterim"
    g = json_oku(dizin / "ayar.json", {})
    bugun = date.fromisoformat(g["bugun"])
    with tempfile.TemporaryDirectory() as t:
        shutil.copytree(dizin / "durum", Path(t) / "durum")
        r = calistir(Path(t) / "durum", True, "yok", bugun, indir=None, cikti=cikti, en_fazla=1)
    return r


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Mevsim toplayıcısı: kaynakları tarar, öneri açar (asla yayınlamaz).")
    p.add_argument("--kuru", action="store_true", help="Kuru çalıştırma: öneri açma, dosya yazma, yalnızca raporla")
    p.add_argument("--kaynak", default=None, choices=KAYNAK_SIRASI + ["hepsi"], help="Yalnızca bu kaynak")
    p.add_argument("--durum-dizini", type=Path, default=KOK / "durum")
    p.add_argument("--bugun", default=None, help="YYYY-MM-DD (deneme için)")
    p.add_argument("--gosterim", action="store_true", help="Örnek veriyle bir öneri göster (kuru)")
    a = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if a.gosterim:
        gosterim()
        return 0
    bugun = date.fromisoformat(a.bugun) if a.bugun else K.bugun_tr()
    tek = None if a.kaynak in (None, "hepsi") else a.kaynak
    gh = None if a.kuru else GitHub(KOK)
    calistir(a.durum_dizini, a.kuru, tek, bugun, github=gh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
