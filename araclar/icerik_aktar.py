#!/usr/bin/env python3
"""İçerik aktarıcısı (yeniden çalıştırılabilir; tüm bölgeler).

Uygulama klasöründeki onaylı taslaklardan kaynak/urunler/<id>.json,
kaynak/tarifler/<id>.json ve kaynak/gorseller.json dosyalarını üretir.

Girdiler (--girdi = mevsim_app klasörü):
  veri_taslak/icerik_sebze_ot.json, icerik_meyve_diger_yoresel.json, icerik_balik.json, icerik_akdeniz.json
  araclar/katalog_urunler.py            (kanonik ürün kimlikleri ve kategoriler)
  docs/05_gorsel_lisans_kaydi.md        (görsel lisans kaydı)
  assets_kaynak/webp/<id>.webp          (bitmiş fotoğraflar)
Bu klasördeki elle bakımlı dosyalar:
  araclar/mevsim/<bolge_id>.json        (bölge başına sezon satırları + kaynak listesi; ör. ege.json, akdeniz.json)
  araclar/bilinirlik.json               (kategori içi tanınırlık sırası: bilinirlik + siralama)

Bölge dosyası: {"aciklama", "arastirma_tarihi", "kaynaklar": {kod: {ad, link}}, "satirlar": [...]}.
Satırın kaynağı ya "kaynaklar" (kod listesi) ya da doğrudan "kaynak_adi" + "kaynak_link" ile yazılır.
Bir dosyadaki satırlar yalnızca o bölgeyi (bölge, alt bölge, bölgenin illeri) ya da bölgenin
kıyısındaki denizi kapsayabilir. Balık ve deniz ürünleri yalnızca deniz satırı alır; başka denizin
balığı bir bölgenin pazarına gelse de o denizin kendi kaydıyla görünür.

Yöresel ürün taslağında "besin", "enerji_*", "secim_ipuclari", "hazirlama_*" ya da "tarifler"
alanı hiç yazılmamışsa ana ürününden (ana_urun_id) alınır; tarifler kopyalanmaz, ana ürünün
tariflerine bağlanır.

Kullanım:  python araclar/icerik_aktar.py --girdi "../mevsim_app"
Sonra:     python araclar/derle.py --kontrol
Yalnızca Python standart kütüphanesi kullanılır.
"""
from __future__ import annotations

import argparse
import json
import re
import runpy
import sys
from collections import defaultdict
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
MEVSIM_KLASORU = Path(__file__).resolve().parent / "mevsim"
ICERIK = ["icerik_sebze_ot.json", "icerik_meyve_diger_yoresel.json", "icerik_balik.json", "icerik_akdeniz.json"]
KATALOG_KATEGORI = {"SEBZE": "sebze", "MEYVE": "meyve", "BALIK": "balik_deniz"}
DIGER_ALT = {"ot": "ot", "diger": "diger"}
# Yöresel ürün taslağında hiç yazılmamışsa ana üründen alınan alanlar
MIRAS_ALANLARI = ("besin", "enerji_kcal_100g", "enerji_durum", "enerji_kaynak_adi", "enerji_kaynak_link",
                  "secim_ipuclari", "hazirlama_adimlari", "hazirlama_kaynak_adi", "hazirlama_kaynak_link",
                  "tarifler")

# Aynı yemeğin iki ajan tarafından farklı kimlikle yazılmış kopyaları -> tutulacak kimlik
TARIF_BIRLESTIR = {
    "biber_kizartmasi": "yogurtlu_biber_kizartmasi",
    "kozlenmis_kapya_salatasi": "kozlenmis_biber_salatasi",
}
EN_FAZLA_TARIF = 3

# Bilinen düzeltmeler (PR açıklamasında listelenir)
ENERJI_DUZELT = {
    # CREA 122800 "Sardine / Pilchard, raw": 225 kcal (943 kJ), yağ 15,4 g, protein 20,3 g — çiğ taze kaydı, değer doğru.
    "sardalya": {"enerji_durum": "çiğ; ölçüm yağlı döneme yakın, kış sardalyasında değer daha düşüktür"},
}
TARIF_ALANLARI = ("id", "baslik", "malzemeler", "adimlar", "kaynak_adi")
BESIN_ALANLARI = ("ad", "tur", "aciklama", "kaynak_adi", "kaynak_link")
KABUL_DURUM = ("kullanılabilir", "geliştirilebilir")
YASAK_METIN = re.compile(r"K-(?:CI|HAL|R|A|H)\d|[a-z0-9._-]+@[a-z0-9-]+\.[a-z]{2,}", re.I)


def json_oku(yol: Path):
    return json.loads(yol.read_text(encoding="utf-8"))


def json_yaz(yol: Path, veri) -> None:
    yol.write_text(json.dumps(veri, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def katalog_oku(girdi: Path) -> dict:
    mod = runpy.run_path(str(girdi / "araclar" / "katalog_urunler.py"))
    kat = {}
    for grup, liste in ((g, mod[g]) for g in ("SEBZE", "MEYVE", "DIGER", "BALIK")):
        for t in liste:
            alt = t[4] if len(t) > 4 else None
            kat[t[0]] = {"ad": t[1], "kategori": KATALOG_KATEGORI.get(grup) or DIGER_ALT.get(alt), "yoresel": alt == "yoresel"}
    return kat


def gorseller_oku(girdi: Path) -> dict:
    """Lisans kaydındaki ürün ayrıntılarından kabul edilen fotoğrafları okur."""
    metin = (girdi / "docs" / "05_gorsel_lisans_kaydi.md").read_text(encoding="utf-8")
    webp = {p.stem for p in (girdi / "assets_kaynak" / "webp").glob("*.webp") if not p.stem.endswith("_k")}
    sonuc, ayni = {}, {}
    for bolum in re.split(r"\n(?=### )", metin):
        m = re.match(r"### .*? \(`(\w+)`\) — \*\*(.*?)\*\*", bolum)
        if not m or not m.group(2).startswith(KABUL_DURUM):
            continue
        gid = m.group(1)
        f = dict(re.findall(r"- \*\*(.*?):\*\* (.*)", bolum))
        esi = re.match(r"`(\w+)` ile aynı fotoğraf", f.get("Not", ""))
        if esi:  # ör. yöresel ürün ana ürünün, barbunya tekirin fotoğrafını kullanır
            ayni[gid] = esi.group(1)
            continue
        if gid not in webp:
            continue
        if "Dosya" in f:
            parca = [p.strip() for p in f["Dosya"].split(" — ")]
            dosya, site = parca[0], parca[1] if len(parca) > 1 else ""
            link = next((p for p in parca if p.startswith("http")), None)
        else:
            dosya, site, link = f.get("Dosya adı", ""), f.get("Kaynak site", ""), f.get("Sayfa")
        lisans_parca = [p.strip() for p in f.get("Lisans", "").split(" — ")]
        lisans_link = next((p.split()[0] for p in lisans_parca[1:] if p.startswith("http")), None)
        yazar = f.get("Yazar") or None
        if "sahibi" in (yazar or "") or "kendi" in site.lower():
            kayit = {"id": gid, "kaynak_adi": "Uygulama sahibinin kendi fotoğrafı", "kaynak_link": None,
                     "yazar": "Uygulama sahibi", "lisans": "Kendi eserimiz (atıf gerekmez)", "lisans_link": None}
        else:
            kayit = {"id": gid, "kaynak_adi": f"{site}: {dosya}" if site else dosya, "kaynak_link": link,
                     "yazar": yazar, "lisans": lisans_parca[0], "lisans_link": lisans_link}
        kayit["duzenleme_notu"] = f.get("Yapılan değişiklik") or None
        sonuc[gid] = kayit
    esleme = {gid: esi for gid, esi in ayni.items() if esi in sonuc}
    return sonuc, esleme


def bilinirlik_oku(yol: Path, urunler: dict, kategori: dict, hatalar: list) -> dict:
    """bilinirlik.json -> {urun_id: (bilinirlik, siralama)}; sıra ve düzey kurallarını denetler."""
    veri = json_oku(yol)
    sonuc = {}
    for kat, liste in veri.items():
        if kat == "aciklama":
            continue
        onceki_duzey, yoresel_goruldu = 0, False
        for sira, (uid, duzey) in enumerate(liste, start=1):
            if uid in sonuc:
                hatalar.append(f"bilinirlik: {uid} iki kez yazılmış")
            if kategori.get(uid) != kat:
                hatalar.append(f"bilinirlik: {uid} '{kat}' listesinde ama kategorisi {kategori.get(uid)}")
            if not isinstance(duzey, int) or not 1 <= duzey <= 5:
                hatalar.append(f"bilinirlik: {uid} düzeyi 1-5 arası olmalı")
                continue
            if duzey < onceki_duzey:
                hatalar.append(f"bilinirlik: {uid} ({duzey}) daha az bilinen bir üründen sonra yazılmış")
            if duzey != onceki_duzey:
                yoresel_goruldu = False
            yoresel = bool((urunler.get(uid) or {}).get("yoresel_il_id"))
            if yoresel_goruldu and not yoresel:
                hatalar.append(f"bilinirlik: genel ürün {uid}, aynı düzeydeki yöresel ürünlerden sonra yazılmış")
            yoresel_goruldu = yoresel_goruldu or yoresel
            if (urunler.get(uid) or {}).get("az_bilinen") and duzey < 3:
                hatalar.append(f"bilinirlik: az bilinen {uid} en az 3 olmalı")
            onceki_duzey = duzey
            sonuc[uid] = (duzey, sira)
    for uid in set(kategori) - set(sonuc):
        hatalar.append(f"bilinirlik: {uid} sıralama dosyasında yok")
    return sonuc


def mevsim_satirlari_oku(klasor: Path, ortak: Path, hatalar: list) -> dict:
    """araclar/mevsim/<bolge_id>.json dosyalarını bölge sırasıyla okur.

    Dönüş: {urun_id: [satır, ...]}; her satırda kaynak_adi, kaynak_link ve arastirma_tarihi çözülmüştür.
    Bir dosya yalnızca kendi bölgesini ya da o bölgenin kıyısındaki denizi kapsayabilir.
    """
    bolgeler = {b["id"]: b["sira"] for b in json_oku(ortak / "bolgeler.json")}
    il_bolge = {i["id"]: i["bolge_id"] for i in json_oku(ortak / "iller.json")}
    alt_bolge = {a["id"]: a["bolge_id"] for a in json_oku(ortak / "alt_bolgeler.json")}
    bolge_deniz = {(b["bolge_id"], b["deniz_id"]) for b in json_oku(ortak / "bolge_deniz.json")}
    dosyalar = sorted(klasor.glob("*.json"), key=lambda p: (bolgeler.get(p.stem, 99), p.stem))
    sonuc = defaultdict(list)
    for yol in dosyalar:
        bolge = yol.stem
        if bolge not in bolgeler:
            hatalar.append(f"mevsim/{yol.name}: dosya adı bir bölge kimliği olmalı")
            continue
        veri = json_oku(yol)
        kaynaklar = veri.get("kaynaklar") or {}
        for n, s in enumerate(veri["satirlar"], start=1):
            on = f"mevsim/{yol.name} satır {n} ({s.get('urun_id')})"
            tur, kid = s["kapsam_turu"], s["kapsam_id"]
            ust = {"bolge": kid, "il": il_bolge.get(kid), "alt_bolge": alt_bolge.get(kid)}.get(tur)
            if tur == "deniz":
                if (bolge, kid) not in bolge_deniz:
                    hatalar.append(f"{on}: {kid} denizi {bolge} bölgesinin kıyısında değil")
            elif not (tur == "il" and kid is None) and ust != bolge:
                hatalar.append(f"{on}: {tur} {kid} bu dosyanın bölgesine ({bolge}) ait değil")
            if "kaynak_adi" in s:
                ad, link = s["kaynak_adi"], s.get("kaynak_link")
            else:
                adlar = []
                for k in s["kaynaklar"]:
                    if k not in kaynaklar:
                        hatalar.append(f"{on}: bilinmeyen kaynak kodu {k}")
                        continue
                    a = kaynaklar[k]["ad"]
                    if k == "K-R4" and s.get("teblig_maddesi"):
                        a += f", madde {s['teblig_maddesi']}"
                    adlar.append(a)
                ad = "; ".join(adlar)
                link = next((kaynaklar[k]["link"] for k in s["kaynaklar"] if k in kaynaklar and kaynaklar[k]["link"]), None)
            sonuc[s["urun_id"]].append({**s, "kaynak_adi": ad, "kaynak_link": link,
                                        "arastirma_tarihi": veri["arastirma_tarihi"]})
    return sonuc


def mevsimler_kur(uid: str, satirlar: list, yoresel_il: str | None) -> list:
    sayac = defaultdict(int)
    kayitlar = []
    for s in satirlar:
        tur, kid = s["kapsam_turu"], s["kapsam_id"]
        if tur == "il" and kid is None:
            kid = yoresel_il
        sayac[(kid, s["donem_turu"])] += 1
        kayitlar.append({
            "id": f"{uid}__{kid}__{s['donem_turu']}__{sayac[(kid, s['donem_turu'])]}",
            "kapsam_turu": tur, "kapsam_id": kid, "donem_turu": s["donem_turu"],
            "bas": s["bas"], "bit": s["bit"], "kaynak_adi": s["kaynak_adi"], "kaynak_link": s["kaynak_link"],
            "arastirma_tarihi": s["arastirma_tarihi"], "guven": s["guven"], "not": s["not"],
        })
    return kayitlar


def miras_uygula(urunler: dict, hatalar: list) -> None:
    """Yöresel üründe hiç yazılmamış alanları ana üründen alır (yerinde)."""
    for uid, u in urunler.items():
        ana_id = u.get("ana_urun_id")
        if not u.get("yoresel_il_id") or not ana_id:
            continue
        ana = urunler.get(ana_id)
        if ana is None:
            hatalar.append(f"{uid}: ana ürün {ana_id} bulunamadı")
            continue
        for alan in MIRAS_ALANLARI:
            if alan not in u:
                u[alan] = ana.get(alan)
        if "enerji_durum" not in u.get("_yazilan", ()) and u.get("enerji_kcal_100g") is not None \
                and u.get("enerji_durum") and "genel değeri" not in u["enerji_durum"]:
            u["enerji_durum"] = f"{u['enerji_durum']} ({ana['ad'].lower()} genel değeri)"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--girdi", type=Path, default=KOK.parent / "mevsim_app")
    p.add_argument("--kaynak", type=Path, default=KOK / "kaynak")
    a = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    hatalar = []
    katalog = katalog_oku(a.girdi)
    satir_urun = mevsim_satirlari_oku(MEVSIM_KLASORU, a.kaynak / "ortak", hatalar)
    gorseller, gorsel_esi = gorseller_oku(a.girdi)  # gorsel_esi: urun_id -> başka ürünün görsel kimliği

    urunler, tarifler, kopya = {}, {}, []
    for dosya in ICERIK:
        yol = a.girdi / "veri_taslak" / dosya
        if not yol.exists():
            continue
        d = json_oku(yol)
        for u in d["urunler"]:
            if u["urun_id"] in urunler:
                hatalar.append(f"içerik iki kez yazılmış: {u['urun_id']}")
            urunler[u["urun_id"]] = {**u, "_yazilan": tuple(u)}
        for t in d["tarifler"]:
            tid = TARIF_BIRLESTIR.get(t["id"], t["id"])
            if tid in tarifler:
                kopya.append(t["id"])
                continue
            if tid == t["id"]:
                tarifler[tid] = {k: t[k] for k in TARIF_ALANLARI if k in t}
    miras_uygula(urunler, hatalar)

    for uid in set(satir_urun) - set(urunler):
        hatalar.append(f"sezon tablosundaki ürünün içeriği yok: {uid}")
    for uid in set(katalog) - set(urunler):
        hatalar.append(f"katalogdaki ürünün içeriği yok: {uid}")

    cikti, gorselsiz, kcal_yok = {}, [], []
    for uid, u in urunler.items():
        ciftlik = u.get("uretim_sekli") == "ciftlik"
        if uid in katalog:
            kat = katalog[uid]["kategori"]
            if katalog[uid]["yoresel"]:
                kat = katalog[u["ana_urun_id"]]["kategori"]
        elif ciftlik or uid == "midye":  # çiftlik eşleri ve midye katalogda ayrı satır değil
            kat = "balik_deniz"
        else:
            hatalar.append(f"katalogda olmayan ürün: {uid}")
            continue
        yoresel_il = u.get("yoresel_il_id")
        bagli = []
        for t in u.get("tarifler") or []:
            t = TARIF_BIRLESTIR.get(t, t)
            if t not in bagli:
                bagli.append(t)
        bagli = bagli[:EN_FAZLA_TARIF]
        kayit = {
            "id": uid, "ad": u["ad"], "diger_adlar": u.get("diger_adlar") or [], "kategori_id": kat,
            "kisa_tanim": u.get("kisa_tanim"), "uretim_sekli": "ciftlik" if ciftlik else "dogal",
            "yil_boyu": bool(ciftlik), "ilgili_urun_id": u.get("ilgili_urun_id"), "yoresel_il_id": yoresel_il,
            "gorsel_id": gorsel_esi.get(uid) or (uid if uid in gorseller else None), "aktif": True,
            "enerji_kcal_100g": u.get("enerji_kcal_100g"), "enerji_durum": u.get("enerji_durum"),
            "enerji_kaynak_adi": u.get("enerji_kaynak_adi"), "enerji_kaynak_link": u.get("enerji_kaynak_link"),
            "az_bilinen": bool(u.get("az_bilinen")), "bilinirlik": None, "siralama": None, "tanitim": u.get("tanitim"),
            "hazirlama_adimlari": u.get("hazirlama_adimlari") or [],
            "hazirlama_kaynak_adi": u.get("hazirlama_kaynak_adi"), "hazirlama_kaynak_link": u.get("hazirlama_kaynak_link"),
            "mevsimler": [] if ciftlik else mevsimler_kur(uid, satir_urun.get(uid, []), yoresel_il),
            "secim_ipuclari": u.get("secim_ipuclari") or [],
            "besin": [{k: b.get(k) for k in BESIN_ALANLARI} for b in u.get("besin") or []],
            "tarifler": bagli,
        }
        if ciftlik and kayit["gorsel_id"] is None and u.get("ilgili_urun_id") in gorseller:
            kayit["gorsel_id"] = u["ilgili_urun_id"]  # aynı tür: doğal karşılığının fotoğrafı
        kayit.update(ENERJI_DUZELT.get(uid, {}))
        if ciftlik and satir_urun.get(uid):
            hatalar.append(f"çiftlik ürününe sezon satırı bağlanmış: {uid}")
        if not ciftlik and not kayit["mevsimler"]:
            hatalar.append(f"doğal ürünün sezon satırı yok: {uid}")
        if kat == "balik_deniz" and any(m["kapsam_turu"] != "deniz" for m in kayit["mevsimler"]):
            hatalar.append(f"balık / deniz ürünü yalnızca deniz satırı alır (bölge satırı var): {uid}")
        if kayit["gorsel_id"] is None:
            gorselsiz.append(uid)
        if kayit["enerji_kcal_100g"] is None:
            kcal_yok.append(uid)
        cikti[uid] = kayit

    # Tanınırlık sırası (yöresel ürünün kendi yoresel_il_id'si içerik taslağından gelir)
    bilinirlik = bilinirlik_oku(Path(__file__).with_name("bilinirlik.json"),
                                {uid: {**urunler[uid], "az_bilinen": k["az_bilinen"]} for uid, k in cikti.items()},
                                {uid: k["kategori_id"] for uid, k in cikti.items()}, hatalar)
    for uid, (duzey, sira) in bilinirlik.items():
        if uid in cikti:
            cikti[uid]["bilinirlik"], cikti[uid]["siralama"] = duzey, sira

    # Acıpayam Çakır Havucu: tescil No 1897'ye göre turuncu Nantes tipi havuç; mor/siyah ifadesi kalmamalı
    acipayam = json.dumps(cikti.get("acipayam_havucu", {}), ensure_ascii=False).lower()
    if "mor " in acipayam or "siyah" in acipayam or "nantes" not in acipayam:
        hatalar.append("acipayam_havucu: açıklama turuncu Nantes tipine göre düzeltilmeli")

    kullanilan = {t for u in cikti.values() for t in u["tarifler"]}
    for t in kullanilan - set(tarifler):
        hatalar.append(f"bilinmeyen tarif: {t}")
    metin = json.dumps([cikti, tarifler, gorseller], ensure_ascii=False)
    for m in sorted(set(YASAK_METIN.findall(metin))):
        hatalar.append(f"yayına girmemesi gereken ifade: {m!r}")
    if hatalar:
        for h in hatalar:
            print("HATA:", h)
        return 1

    for klasor in ("urunler", "tarifler"):
        (a.kaynak / klasor).mkdir(parents=True, exist_ok=True)
        for eski in (a.kaynak / klasor).glob("*.json"):
            eski.unlink()
    for uid, kayit in sorted(cikti.items()):
        json_yaz(a.kaynak / "urunler" / f"{uid}.json", kayit)
    for tid in sorted(kullanilan):
        json_yaz(a.kaynak / "tarifler" / f"{tid}.json", tarifler[tid])
    json_yaz(a.kaynak / "gorseller.json", [gorseller[g] for g in sorted({u["gorsel_id"] for u in cikti.values() if u["gorsel_id"]})])

    sayilar = defaultdict(int)
    for u in cikti.values():
        sayilar["yöresel" if u["yoresel_il_id"] else u["kategori_id"]] += 1
    print(f"{len(cikti)} ürün ({dict(sayilar)}), "
          f"{sum(len(u['mevsimler']) for u in cikti.values())} mevsim kaydı, {len(kullanilan)} tarif, "
          f"{sum(1 for u in cikti.values() if u['gorsel_id'])} görselli ürün")
    print("Birleştirilen tarif kopyaları:", ", ".join(sorted(kopya)))
    print("Görseli henüz olmayan:", ", ".join(sorted(gorselsiz)))
    print("Enerji değeri olmayan:", ", ".join(sorted(kcal_yok)))
    print("Hazırlama adımı olan:", sum(1 for u in cikti.values() if u["hazirlama_adimlari"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
