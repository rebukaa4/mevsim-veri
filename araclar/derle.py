#!/usr/bin/env python3
"""Mevsim veri derleyicisi.

kaynak/ altındaki dosyaları okur, sema/v1.schema.json ve iş kurallarıyla
doğrular, yayin/v1/mevsim_veri.json ve yayin/v1/surum.json üretir.
Yalnızca Python standart kütüphanesi kullanılır.

Kullanım:
  python araclar/derle.py                 # doğrula + yayin/ klasörüne yaz
  python araclar/derle.py --kontrol       # yalnızca doğrula (PR kontrolü)
  python araclar/derle.py --veri-surumu 7 --onceki eski_mevsim_veri.json

Çıkış kodu: 0 = sorunsuz, 1 = doğrulama hatası.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
SEMA_SURUMU = 1
UST_SINIR_BAYT = 10 * 1024 * 1024
ORNEK_ON_EK = "ornek_"
TSI = timezone(timedelta(hours=3))

# Ay başına gün sınırı; 02-29 her zaman kabul edilir (mimari belge 2.6).
AY_GUN = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

# Kaynak dosyalarda yazılmayabilecek alanlar ve varsayılan değerleri.
URUN_VARSAYILAN = {
    "diger_adlar": [], "kisa_tanim": None, "yil_boyu": False, "ilgili_urun_id": None,
    "yoresel_il_id": None, "gorsel_id": None, "aktif": True,
    "enerji_kcal_100g": None, "enerji_durum": None, "enerji_kaynak_adi": None, "enerji_kaynak_link": None,
    "az_bilinen": False, "tanitim": None, "hazirlama_adimlari": [],
    "hazirlama_kaynak_adi": None, "hazirlama_kaynak_link": None,
    "mevsimler": [], "secim_ipuclari": [], "besin": [], "tarifler": [],
}
MEVSIM_VARSAYILAN = {"kaynak_link": None, "not": None}
BESIN_VARSAYILAN = {"aciklama": None, "kaynak_adi": None, "kaynak_link": None}
TARIF_VARSAYILAN = {"kaynak_adi": None}
GORSEL_VARSAYILAN = {"kaynak_link": None, "yazar": None, "lisans_link": None, "duzenleme_notu": None}
ALT_BOLGE_VARSAYILAN = {"aciklama": None}
IL_VARSAYILAN = {"alt_bolge_id": None}
NOT_VARSAYILAN = {"kapsam_turu": None, "kapsam_id": None, "kaynak_link": None, "bildirimde_goster": False}

ORTAK_DOSYALAR = {
    "kategoriler": "kategoriler.json", "bolgeler": "bolgeler.json", "alt_bolgeler": "alt_bolgeler.json",
    "iller": "iller.json", "denizler": "denizler.json", "bolge_deniz": "bolge_deniz.json",
    "il_deniz": "il_deniz.json",
}


# --------------------------------------------------------------------------
# Yalın JSON Schema doğrulayıcı (sema dosyasında kullanılan alt küme)
# --------------------------------------------------------------------------
def _tip_uyar(deger, tip: str) -> bool:
    if tip == "null":
        return deger is None
    if tip == "boolean":
        return isinstance(deger, bool)
    if tip == "integer":
        return isinstance(deger, int) and not isinstance(deger, bool)
    if tip == "number":
        return isinstance(deger, (int, float)) and not isinstance(deger, bool)
    if tip == "string":
        return isinstance(deger, str)
    if tip == "array":
        return isinstance(deger, list)
    if tip == "object":
        return isinstance(deger, dict)
    raise ValueError(f"Desteklenmeyen tip: {tip}")


def sema_dogrula(deger, sema: dict, kok_sema: dict, yol: str, hatalar: list[str]) -> None:
    if "$ref" in sema:
        ref = sema["$ref"]
        if not ref.startswith("#/$defs/"):
            raise ValueError(f"Desteklenmeyen $ref: {ref}")
        sema_dogrula(deger, kok_sema["$defs"][ref[len("#/$defs/"):]], kok_sema, yol, hatalar)
        return
    if "const" in sema and deger != sema["const"]:
        hatalar.append(f"{yol}: değer {sema['const']!r} olmalı, {deger!r} bulundu")
        return
    if "enum" in sema and deger not in sema["enum"]:
        izinli = ", ".join("boş" if e is None else str(e) for e in sema["enum"])
        hatalar.append(f"{yol}: {deger!r} geçersiz; izin verilenler: {izinli}")
        return
    if "type" in sema:
        tipler = sema["type"] if isinstance(sema["type"], list) else [sema["type"]]
        if not any(_tip_uyar(deger, t) for t in tipler):
            hatalar.append(f"{yol}: tip {'/'.join(tipler)} olmalı, {type(deger).__name__} bulundu")
            return
    if isinstance(deger, str):
        if "minLength" in sema and len(deger.strip()) < sema["minLength"]:
            hatalar.append(f"{yol}: boş olamaz")
        if "pattern" in sema and not re.search(sema["pattern"], deger):
            hatalar.append(f"{yol}: {deger!r} biçimi geçersiz")
    if isinstance(deger, (int, float)) and not isinstance(deger, bool):
        if "minimum" in sema and deger < sema["minimum"]:
            hatalar.append(f"{yol}: {deger} en az {sema['minimum']} olmalı")
        if "maximum" in sema and deger > sema["maximum"]:
            hatalar.append(f"{yol}: {deger} en fazla {sema['maximum']} olmalı")
    if isinstance(deger, list):
        if "minItems" in sema and len(deger) < sema["minItems"]:
            hatalar.append(f"{yol}: en az {sema['minItems']} madde olmalı")
        if "items" in sema:
            for i, madde in enumerate(deger):
                sema_dogrula(madde, sema["items"], kok_sema, f"{yol}[{i}]", hatalar)
    if isinstance(deger, dict):
        for alan in sema.get("required", []):
            if alan not in deger:
                hatalar.append(f"{yol}: zorunlu alan eksik: {alan}")
        ozellikler = sema.get("properties", {})
        if sema.get("additionalProperties") is False:
            for alan in deger:
                if alan not in ozellikler:
                    hatalar.append(f"{yol}: tanımsız alan: {alan}")
        for alan, alt_sema in ozellikler.items():
            if alan in deger:
                sema_dogrula(deger[alan], alt_sema, kok_sema, f"{yol}.{alan}", hatalar)


# --------------------------------------------------------------------------
# Kaynak okuma
# --------------------------------------------------------------------------
def _json_oku(yol: Path, hatalar: list[str]):
    try:
        with open(yol, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        hatalar.append(f"{yol.name}: JSON okunamadı (satır {e.lineno}, sütun {e.colno}): {e.msg}")
    except OSError as e:
        hatalar.append(f"{yol}: dosya okunamadı: {e}")
    return None


def _varsayilan(nesne, varsayilan: dict):
    if not isinstance(nesne, dict):
        return nesne
    sonuc = dict(nesne)
    for k, v in varsayilan.items():
        if k not in sonuc:
            sonuc[k] = list(v) if isinstance(v, list) else v
    return sonuc


def _liste_varsayilan(liste, varsayilan: dict):
    return [_varsayilan(x, varsayilan) for x in liste] if isinstance(liste, list) else liste


def _urun_normallestir(u):
    u = _varsayilan(u, URUN_VARSAYILAN)
    if isinstance(u, dict):
        u["mevsimler"] = _liste_varsayilan(u.get("mevsimler"), MEVSIM_VARSAYILAN)
        u["besin"] = _liste_varsayilan(u.get("besin"), BESIN_VARSAYILAN)
    return u


def kaynak_oku(kaynak: Path, hatalar: list[str]) -> dict:
    veri: dict = {}
    ortak = kaynak / "ortak"
    for anahtar, dosya in ORTAK_DOSYALAR.items():
        icerik = _json_oku(ortak / dosya, hatalar)
        veri[anahtar] = icerik if icerik is not None else []
    veri["alt_bolgeler"] = _liste_varsayilan(veri["alt_bolgeler"], ALT_BOLGE_VARSAYILAN)
    veri["iller"] = _liste_varsayilan(veri["iller"], IL_VARSAYILAN)

    gorsel_dosya = kaynak / "gorseller.json"
    gorseller = _json_oku(gorsel_dosya, hatalar) if gorsel_dosya.exists() else []
    veri["gorseller"] = _liste_varsayilan(gorseller or [], GORSEL_VARSAYILAN)

    veri["urunler"] = []
    for yol in sorted((kaynak / "urunler").glob("*.json")):
        u = _json_oku(yol, hatalar)
        if u is None:
            continue
        if isinstance(u, dict) and u.get("id") != yol.stem:
            hatalar.append(f"urunler/{yol.name}: dosya adı ürün kimliğiyle aynı olmalı (id={u.get('id')!r})")
        veri["urunler"].append(_urun_normallestir(u))

    veri["tarifler"] = []
    for yol in sorted((kaynak / "tarifler").glob("*.json")):
        t = _json_oku(yol, hatalar)
        if t is None:
            continue
        if isinstance(t, dict) and t.get("id") != yol.stem:
            hatalar.append(f"tarifler/{yol.name}: dosya adı tarif kimliğiyle aynı olmalı (id={t.get('id')!r})")
        veri["tarifler"].append(_varsayilan(t, TARIF_VARSAYILAN))

    veri["yil_notlari"] = []
    for yol in sorted((kaynak / "notlar").glob("*/*.json")):
        n = _json_oku(yol, hatalar)
        if n is None:
            continue
        if isinstance(n, dict) and n.get("id") != yol.stem:
            hatalar.append(f"notlar/{yol.parent.name}/{yol.name}: dosya adı not kimliğiyle aynı olmalı")
        veri["yil_notlari"].append(_varsayilan(n, NOT_VARSAYILAN))
    return veri


# --------------------------------------------------------------------------
# İş kuralları (mimari belge 3.3, madde 6-10)
# --------------------------------------------------------------------------
def _gun_ay_gecerli(metin) -> bool:
    if not isinstance(metin, str) or not re.fullmatch(r"\d{2}-\d{2}", metin):
        return False
    ay, gun = int(metin[:2]), int(metin[3:])
    return 1 <= ay <= 12 and 1 <= gun <= AY_GUN[ay]


def _tarih_gecerli(metin) -> bool:
    try:
        date.fromisoformat(metin)
        return isinstance(metin, str) and len(metin) == 10
    except (TypeError, ValueError):
        return False


# Uygulamada fiyat gösterilmez; notlar ve kısa tanımlar arz diliyle yazılır ("en bol olduğu dönem").
# Yalnızca tam kelimeler: "tatlı", "patlıcan", "çeşitler" gibi içinde "tl" geçen sözcükler takılmaz.
# "TL" ve "lira" yanında bir sayı varsa fiyat sayılır ("40 TL", "TL 15", "25 liraya"); ₺ her zaman.
FIYAT_DILI = re.compile(
    r"\bucuz\w*|\bpahal\w*|\bfiyat\w*|₺"
    r"|\d[\d.,]*\s*(?:TL|lira\w*)\b|\b(?:TL|lira)\s*\d",
    re.IGNORECASE)


def _fiyat_dili(metin) -> bool:
    return isinstance(metin, str) and bool(FIYAT_DILI.search(metin))


def _dolu(metin) -> bool:
    return isinstance(metin, str) and metin.strip() != ""


def kurallari_dogrula(veri: dict, hatalar: list[str], uyarilar: list[str], onceki: dict | None = None) -> None:
    def kimlikler(anahtar, alan="id"):
        gorulen, tekrar = set(), set()
        for x in veri.get(anahtar, []):
            if isinstance(x, dict) and isinstance(x.get(alan), str):
                (tekrar if x[alan] in gorulen else gorulen).add(x[alan])
        for k in sorted(tekrar, key=str):
            hatalar.append(f"{anahtar}: tekrar eden kimlik: {k}")
        return gorulen

    kategori = kimlikler("kategoriler")
    bolge = kimlikler("bolgeler")
    alt_bolge = kimlikler("alt_bolgeler")
    il = kimlikler("iller")
    deniz = kimlikler("denizler")
    gorsel = kimlikler("gorseller")
    urun = kimlikler("urunler")
    tarif = kimlikler("tarifler")
    kimlikler("yil_notlari")

    kapsamlar = {"bolge": bolge, "alt_bolge": alt_bolge, "il": il, "deniz": deniz}
    alt_bolge_ust = {a["id"]: a.get("bolge_id") for a in veri.get("alt_bolgeler", []) if isinstance(a, dict)}
    il_bilgi = {i["id"]: i for i in veri.get("iller", []) if isinstance(i, dict) and "id" in i}

    # Ortak tablolar arası başvurular
    for a in veri.get("alt_bolgeler", []):
        if isinstance(a, dict) and a.get("bolge_id") not in bolge:
            hatalar.append(f"alt_bolgeler/{a.get('id')}: bilinmeyen bölge: {a.get('bolge_id')}")
    for i in veri.get("iller", []):
        if not isinstance(i, dict):
            continue
        if i.get("bolge_id") not in bolge:
            hatalar.append(f"iller/{i.get('id')}: bilinmeyen bölge: {i.get('bolge_id')}")
        if i.get("alt_bolge_id") is not None:
            if i["alt_bolge_id"] not in alt_bolge:
                hatalar.append(f"iller/{i.get('id')}: bilinmeyen alt bölge: {i['alt_bolge_id']}")
            elif alt_bolge_ust.get(i["alt_bolge_id"]) != i.get("bolge_id"):
                hatalar.append(f"iller/{i.get('id')}: alt bölge {i['alt_bolge_id']} başka bölgeye ait")
    cift = set()
    for b in veri.get("bolge_deniz", []):
        if not isinstance(b, dict):
            continue
        if b.get("bolge_id") not in bolge or b.get("deniz_id") not in deniz:
            hatalar.append(f"bolge_deniz: bilinmeyen bölge/deniz: {b.get('bolge_id')}/{b.get('deniz_id')}")
        cift_k = (b.get("bolge_id"), b.get("deniz_id"))
        if cift_k in cift:
            hatalar.append(f"bolge_deniz: tekrar eden satır: {cift_k[0]}/{cift_k[1]}")
        cift.add(cift_k)
    cift = set()
    for b in veri.get("il_deniz", []):
        if not isinstance(b, dict):
            continue
        if b.get("il_id") not in il or b.get("deniz_id") not in deniz:
            hatalar.append(f"il_deniz: bilinmeyen il/deniz: {b.get('il_id')}/{b.get('deniz_id')}")
        cift_k = (b.get("il_id"), b.get("deniz_id"))
        if cift_k in cift:
            hatalar.append(f"il_deniz: tekrar eden satır: {cift_k[0]}/{cift_k[1]}")
        cift.add(cift_k)

    # Ürünler
    mevsim_kimlikleri: set = set()
    for u in veri.get("urunler", []):
        if not isinstance(u, dict):
            continue
        uid = u.get("id")
        on = f"urunler/{uid}"
        if u.get("kategori_id") not in kategori:
            hatalar.append(f"{on}: bilinmeyen kategori: {u.get('kategori_id')}")
        if u.get("gorsel_id") is not None and u["gorsel_id"] not in gorsel:
            hatalar.append(f"{on}: gorseller.json içinde olmayan görsel: {u['gorsel_id']}")
        if u.get("ilgili_urun_id") is not None:
            if u["ilgili_urun_id"] not in urun:
                hatalar.append(f"{on}: bilinmeyen ilgili ürün: {u['ilgili_urun_id']}")
            elif u["ilgili_urun_id"] == uid:
                hatalar.append(f"{on}: ilgili ürün kendisi olamaz")
        if u.get("yoresel_il_id") is not None and u["yoresel_il_id"] not in il:
            hatalar.append(f"{on}: bilinmeyen yöresel il: {u['yoresel_il_id']}")
        tarifler = u.get("tarifler") or []
        for t in tarifler:
            if t not in tarif:
                hatalar.append(f"{on}: bilinmeyen tarif: {t}")
        if len(set(map(str, tarifler))) != len(tarifler):
            hatalar.append(f"{on}: aynı tarif birden çok kez bağlanmış")

        mevsimler = [m for m in (u.get("mevsimler") or []) if isinstance(m, dict)]
        if u.get("uretim_sekli") == "ciftlik" and u.get("yil_boyu") is not True:
            hatalar.append(f"{on}: çiftlik ürünü yil_boyu: true olmalı")
        if (u.get("uretim_sekli") == "ciftlik" or u.get("yil_boyu") is True) and mevsimler:
            hatalar.append(f"{on}: çiftlik / yıl boyu ürününde mevsim kaydı olamaz")
        if (u.get("uretim_sekli") == "dogal" and u.get("yil_boyu") is not True
                and u.get("aktif") is True and not mevsimler):
            uyarilar.append(f"{on}: doğal ürünün hiç mevsim kaydı yok")

        # Enerji
        kcal = u.get("enerji_kcal_100g")
        if kcal is not None:
            if not isinstance(kcal, int) or isinstance(kcal, bool) or not 0 <= kcal <= 900:
                hatalar.append(f"{on}: enerji_kcal_100g 0-900 arası tamsayı olmalı")
            if not _dolu(u.get("enerji_kaynak_adi")):
                hatalar.append(f"{on}: enerji değeri varsa enerji_kaynak_adi zorunlu")
            if not _dolu(u.get("enerji_durum")):
                uyarilar.append(f"{on}: enerji_durum (ör. 'çiğ, yenebilir kısım') yazılmamış")

        # "Nasıl hazırlanır?" zorunluluğu (Karar 9)
        if u.get("kategori_id") == "ot" or u.get("az_bilinen") is True:
            if not (u.get("hazirlama_adimlari") or []):
                hatalar.append(f"{on}: ot / az bilinen üründe en az bir hazırlama adımı zorunlu")
            if not _dolu(u.get("tanitim")):
                hatalar.append(f"{on}: ot / az bilinen üründe tanıtım metni zorunlu")

        # Fiyat yok kuralı: kullanıcıya görünen kısa tanım ve mevsim notlarında fiyat dili olmaz
        if _fiyat_dili(u.get("kisa_tanim")):
            hatalar.append(f"{on}: kisa_tanim fiyattan söz ediyor (fiyat yok kuralı): {u.get('kisa_tanim')!r}")
        for m in mevsimler:
            if _fiyat_dili(m.get("not")):
                hatalar.append(f"{on}/mevsimler/{m.get('id')}: not fiyattan söz ediyor (fiyat yok kuralı): {m.get('not')!r}")

        # Mevsim kayıtları
        bolge_duzeyi = set()  # (bolge_id, donem_turu)
        for m in mevsimler:
            if m.get("kapsam_turu") == "bolge":
                bolge_duzeyi.add((m.get("kapsam_id"), m.get("donem_turu")))
        for m in mevsimler:
            mid = m.get("id")
            mon = f"{on}/mevsimler/{mid}"
            if mid in mevsim_kimlikleri:
                hatalar.append(f"{mon}: tekrar eden mevsim kimliği")
            mevsim_kimlikleri.add(mid)
            for alan in ("bas", "bit"):
                if not _gun_ay_gecerli(m.get(alan)):
                    hatalar.append(f"{mon}: geçersiz gün-ay {alan}={m.get(alan)!r} (AA-GG)")
            if not _tarih_gecerli(m.get("arastirma_tarihi")):
                hatalar.append(f"{mon}: geçersiz arastirma_tarihi {m.get('arastirma_tarihi')!r}")
            tur, kid = m.get("kapsam_turu"), m.get("kapsam_id")
            if tur in kapsamlar and kid not in kapsamlar[tur]:
                hatalar.append(f"{mon}: bilinmeyen {tur} kapsamı: {kid}")
            if tur == "deniz" and u.get("kategori_id") != "balik_deniz":
                hatalar.append(f"{mon}: deniz kapsamı yalnızca balık/deniz ürünlerinde kullanılır")
            if u.get("yoresel_il_id") is None:
                ust = None
                if tur == "il" and kid in il_bilgi:
                    ust = il_bilgi[kid].get("bolge_id")
                elif tur == "alt_bolge" and kid in alt_bolge_ust:
                    ust = alt_bolge_ust[kid]
                if ust is not None and (ust, m.get("donem_turu")) not in bolge_duzeyi:
                    hatalar.append(f"{mon}: {tur} düzeyi kaydın '{ust}' bölgesinde aynı dönem türüyle bölge düzeyi kaydı yok")

    # Tanınırlık sırası (isteğe bağlı alanlar): kategori içinde sıra tekrar etmez,
    # az bilinen ürün "herkesin bildiği" düzeyde olamaz.
    kategori_sira: dict = {}
    for u in veri.get("urunler", []):
        if not isinstance(u, dict):
            continue
        on = f"urunler/{u.get('id')}"
        duzey, sira = u.get("bilinirlik"), u.get("siralama")
        if (duzey is None) != (sira is None):
            uyarilar.append(f"{on}: bilinirlik ve siralama birlikte yazılmalı")
        if isinstance(sira, int) and not isinstance(sira, bool):
            anahtar = (u.get("kategori_id"), sira)
            if anahtar in kategori_sira:
                hatalar.append(f"{on}: siralama {sira}, '{u.get('kategori_id')}' kategorisinde "
                               f"{kategori_sira[anahtar]} ile aynı")
            else:
                kategori_sira[anahtar] = u.get("id")
        if u.get("az_bilinen") is True and isinstance(duzey, int) and duzey < 3:
            hatalar.append(f"{on}: az bilinen ürünün bilinirlik değeri en az 3 olmalı")

    # Yıl notları
    for n in veri.get("yil_notlari", []):
        if not isinstance(n, dict):
            continue
        on = f"yil_notlari/{n.get('id')}"
        if n.get("urun_id") not in urun:
            hatalar.append(f"{on}: bilinmeyen ürün: {n.get('urun_id')}")
        tur, kid = n.get("kapsam_turu"), n.get("kapsam_id")
        if (tur is None) != (kid is None):
            hatalar.append(f"{on}: kapsam_turu ve kapsam_id birlikte dolu ya da birlikte boş olmalı")
        elif tur in kapsamlar and kid not in kapsamlar[tur]:
            hatalar.append(f"{on}: bilinmeyen {tur} kapsamı: {kid}")
        tarihler_ok = True
        for alan in ("gecerlilik_bas", "gecerlilik_bit", "onay_tarihi"):
            if not _tarih_gecerli(n.get(alan)):
                hatalar.append(f"{on}: geçersiz tarih {alan}={n.get(alan)!r}")
                tarihler_ok = False
        if tarihler_ok and n["gecerlilik_bas"] > n["gecerlilik_bit"]:
            hatalar.append(f"{on}: geçerlilik başlangıcı bitişten sonra olamaz")

    # Ürün olmayan tarif (uyarı)
    bagli = {t for u in veri.get("urunler", []) if isinstance(u, dict) for t in (u.get("tarifler") or [])}
    for t in sorted(tarif - bagli, key=str):
        uyarilar.append(f"tarifler/{t}: hiçbir ürüne bağlı değil")

    # Önceki yayına göre kontroller (madde 9 ve 10)
    if onceki is not None:
        eski = {u.get("id") for u in onceki.get("urunler", []) if isinstance(u, dict)}
        # "ornek_" ile başlayan kayıtlar yalnızca derleme hattını denemek içindi; kaldırılabilir.
        for k in sorted({e for e in eski - urun if not str(e).startswith(ORNEK_ON_EK)}, key=str):
            hatalar.append(f"urunler/{k}: yayındaki ürün kaldırılamaz; silmek yerine \"aktif\": false yapın")
        eski_gercek = {e for e in eski if not str(e).startswith(ORNEK_ON_EK)}
        yeni_gercek = {u for u in urun if not str(u).startswith(ORNEK_ON_EK)}
        if eski_gercek and len(yeni_gercek) < 0.9 * len(eski_gercek):
            hatalar.append(f"ürün sayısı {len(yeni_gercek)}, önceki yayının ({len(eski_gercek)}) %90'ından az")
        eski_surum = onceki.get("veri_surumu")
        if isinstance(eski_surum, int) and isinstance(veri.get("veri_surumu"), int) and veri["veri_surumu"] <= eski_surum:
            hatalar.append(f"veri_surumu {veri['veri_surumu']} önceki yayından ({eski_surum}) büyük olmalı")

    if not urun:
        hatalar.append("hiç ürün yok")
    for b in sorted(bolge):
        var = any(isinstance(m, dict) and m.get("kapsam_turu") == "bolge" and m.get("kapsam_id") == b
                  for u in veri.get("urunler", []) if isinstance(u, dict) for m in (u.get("mevsimler") or []))
        if not var:
            uyarilar.append(f"bolgeler/{b}: bu bölge için bölge düzeyinde mevsim kaydı yok")


# --------------------------------------------------------------------------
# Derleme
# --------------------------------------------------------------------------
def git_surumu(kok: Path) -> int | None:
    try:
        cikti = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=kok, capture_output=True, text=True, check=True)
        return int(cikti.stdout.strip())
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def derle(kaynak: Path, sema_yolu: Path, veri_surumu: int, onceki: dict | None = None,
          yayin_tarihi: str | None = None) -> tuple[dict, list[str], list[str]]:
    hatalar: list[str] = []
    uyarilar: list[str] = []
    with open(sema_yolu, encoding="utf-8") as f:
        sema = json.load(f)
    icerik = kaynak_oku(kaynak, hatalar)
    veri = {
        "sema_surumu": SEMA_SURUMU,
        "veri_surumu": veri_surumu,
        "yayin_tarihi": yayin_tarihi or datetime.now(TSI).isoformat(timespec="seconds"),
        **icerik,
    }
    sema_dogrula(veri, sema, sema, "kok", hatalar)
    kurallari_dogrula(veri, hatalar, uyarilar, onceki)
    return veri, hatalar, uyarilar


def yaz(veri: dict, cikti: Path) -> dict:
    hedef = cikti / f"v{SEMA_SURUMU}"
    hedef.mkdir(parents=True, exist_ok=True)
    baytlar = json.dumps(veri, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(baytlar) > UST_SINIR_BAYT:
        raise ValueError(f"Yayın dosyası {len(baytlar)} bayt; üst sınır {UST_SINIR_BAYT}")
    (hedef / "mevsim_veri.json").write_bytes(baytlar)
    surum = {
        "sema_surumu": veri["sema_surumu"],
        "veri_surumu": veri["veri_surumu"],
        "yayin_tarihi": veri["yayin_tarihi"],
        "dosya": "mevsim_veri.json",
        "boyut": len(baytlar),
        "sha256": hashlib.sha256(baytlar).hexdigest(),
    }
    (hedef / "surum.json").write_text(json.dumps(surum, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return surum


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Mevsim verisini doğrular ve yayın dosyalarını üretir.")
    p.add_argument("--kaynak", type=Path, default=KOK / "kaynak")
    p.add_argument("--sema", type=Path, default=KOK / "sema" / f"v{SEMA_SURUMU}.schema.json")
    p.add_argument("--cikti", type=Path, default=KOK / "yayin")
    p.add_argument("--veri-surumu", type=int, default=None, help="Varsayılan: git commit sayısı")
    p.add_argument("--onceki", type=Path, default=None, help="Şu an yayındaki mevsim_veri.json (varsa)")
    p.add_argument("--kontrol", action="store_true", help="Yalnızca doğrula, dosya yazma")
    a = p.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    veri_surumu = a.veri_surumu if a.veri_surumu is not None else (git_surumu(KOK) or 1)
    onceki = None
    if a.onceki is not None and a.onceki.exists() and a.onceki.stat().st_size > 0:
        try:
            onceki = json.loads(a.onceki.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"UYARI: önceki yayın dosyası okunamadı, karşılaştırma atlandı: {a.onceki}")

    veri, hatalar, uyarilar = derle(a.kaynak, a.sema, veri_surumu, onceki)
    for u in uyarilar:
        print(f"UYARI: {u}")
    if hatalar:
        print(f"\n{len(hatalar)} HATA bulundu, veri yayınlanamaz:")
        for h in hatalar:
            print(f"  HATA: {h}")
        return 1
    print(f"Doğrulama başarılı: {len(veri['urunler'])} ürün, {len(veri['tarifler'])} tarif, "
          f"{len(veri['yil_notlari'])} yıl notu.")
    if not a.kontrol:
        surum = yaz(veri, a.cikti)
        print(f"Yazıldı: {a.cikti / f'v{SEMA_SURUMU}'} (veri_surumu={surum['veri_surumu']}, "
              f"{surum['boyut']} bayt, sha256={surum['sha256']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
