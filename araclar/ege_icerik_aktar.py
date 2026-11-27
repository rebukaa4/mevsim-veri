#!/usr/bin/env python3
"""Ege ilk veri aktarıcısı (yeniden çalıştırılabilir).

Uygulama klasöründeki onaylı taslaklardan kaynak/urunler/<id>.json,
kaynak/tarifler/<id>.json ve kaynak/gorseller.json dosyalarını üretir.

Girdiler (--girdi = mevsim_app klasörü):
  veri_taslak/icerik_sebze_ot.json, icerik_meyve_diger_yoresel.json, icerik_balik.json
  araclar/katalog_urunler.py            (kanonik ürün kimlikleri ve kategoriler)
  docs/05_gorsel_lisans_kaydi.md        (görsel lisans kaydı)
  assets_kaynak/webp/<id>.webp          (bitmiş fotoğraflar)
Bu klasördeki elle bakımlı dosya:
  araclar/ege_mevsim.json               (sezon satırları + kaynak listesi; 04_ege_urun_tablosu.md'den)

Kullanım:  python araclar/ege_icerik_aktar.py --girdi "../mevsim_app"
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
ICERIK = ["icerik_sebze_ot.json", "icerik_meyve_diger_yoresel.json", "icerik_balik.json"]
KATALOG_KATEGORI = {"SEBZE": "sebze", "MEYVE": "meyve", "BALIK": "balik_deniz"}
DIGER_ALT = {"ot": "ot", "diger": "diger"}

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
YASAK_METIN = re.compile(r"K-(?:CI|HAL|R|A|H)\d|Burak|@[a-z0-9-]+\.[a-z]", re.I)


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
    sonuc = {}
    for bolum in re.split(r"\n(?=### )", metin):
        m = re.match(r"### .*? \(`(\w+)`\) — \*\*(.*?)\*\*", bolum)
        if not m or m.group(1) not in webp or not m.group(2).startswith(KABUL_DURUM):
            continue
        gid = m.group(1)
        f = dict(re.findall(r"- \*\*(.*?):\*\* (.*)", bolum))
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
    return sonuc


def mevsimler_kur(uid: str, satirlar: list, kaynaklar: dict, tarih: str, yoresel_il: str | None) -> list:
    sayac = defaultdict(int)
    kayitlar = []
    for s in satirlar:
        tur, kid = s["kapsam_turu"], s["kapsam_id"]
        if tur == "il" and kid is None:
            kid = yoresel_il
        sayac[(kid, s["donem_turu"])] += 1
        adlar = []
        for k in s["kaynaklar"]:
            ad = kaynaklar[k]["ad"]
            if k == "K-R4" and s.get("teblig_maddesi"):
                ad += f", madde {s['teblig_maddesi']}"
            adlar.append(ad)
        link = next((kaynaklar[k]["link"] for k in s["kaynaklar"] if kaynaklar[k]["link"]), None)
        kayitlar.append({
            "id": f"{uid}__{kid}__{s['donem_turu']}__{sayac[(kid, s['donem_turu'])]}",
            "kapsam_turu": tur, "kapsam_id": kid, "donem_turu": s["donem_turu"],
            "bas": s["bas"], "bit": s["bit"], "kaynak_adi": "; ".join(adlar), "kaynak_link": link,
            "arastirma_tarihi": tarih, "guven": s["guven"], "not": s["not"],
        })
    return kayitlar


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--girdi", type=Path, default=KOK.parent / "mevsim_app")
    p.add_argument("--kaynak", type=Path, default=KOK / "kaynak")
    a = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    katalog = katalog_oku(a.girdi)
    mevsim_veri = json_oku(Path(__file__).with_name("ege_mevsim.json"))
    gorseller = gorseller_oku(a.girdi)

    urunler, tarifler, kopya = {}, {}, []
    for dosya in ICERIK:
        d = json_oku(a.girdi / "veri_taslak" / dosya)
        for u in d["urunler"]:
            urunler[u["urun_id"]] = u
        for t in d["tarifler"]:
            tid = TARIF_BIRLESTIR.get(t["id"], t["id"])
            if tid in tarifler:
                kopya.append(t["id"])
                continue
            if tid == t["id"]:
                tarifler[tid] = {k: t[k] for k in TARIF_ALANLARI if k in t}

    satir_urun = defaultdict(list)
    for s in mevsim_veri["satirlar"]:
        satir_urun[s["urun_id"]].append(s)

    hatalar = []
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
            "gorsel_id": uid if uid in gorseller else None, "aktif": True,
            "enerji_kcal_100g": u.get("enerji_kcal_100g"), "enerji_durum": u.get("enerji_durum"),
            "enerji_kaynak_adi": u.get("enerji_kaynak_adi"), "enerji_kaynak_link": u.get("enerji_kaynak_link"),
            "az_bilinen": bool(u.get("az_bilinen")), "tanitim": u.get("tanitim"),
            "hazirlama_adimlari": u.get("hazirlama_adimlari") or [],
            "hazirlama_kaynak_adi": u.get("hazirlama_kaynak_adi"), "hazirlama_kaynak_link": u.get("hazirlama_kaynak_link"),
            "mevsimler": [] if ciftlik else mevsimler_kur(uid, satir_urun.get(uid, []), mevsim_veri["kaynaklar"],
                                                          mevsim_veri["arastirma_tarihi"], yoresel_il),
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
        if kayit["gorsel_id"] is None:
            gorselsiz.append(uid)
        if kayit["enerji_kcal_100g"] is None:
            kcal_yok.append(uid)
        cikti[uid] = kayit

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
