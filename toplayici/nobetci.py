"""Nöbetçi: toplayıcı uzun süredir çalışmadıysa ya da bir kaynak üst üste okunamıyorsa
TEK bir Türkçe Issue açar/günceller (GitHub depo sahibine e-posta gönderir); düzelince kapatır.

  python toplayici/nobetci.py --durum _durum/durum/son_calisma.json [--kuru]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BURASI = Path(__file__).resolve().parent
ISARET = "[nobetci]"
TR = timezone(timedelta(hours=3))


def sorunlar(son: dict | None, simdi: datetime, ayar: dict) -> tuple[str | None, list[str]]:
    """(başlık, açıklama satırları); sorun yoksa (None, [])."""
    n = ayar["nobetci"]
    if not son or not son.get("son_basarili_calisma"):
        return (f"Toplayıcı hiç çalışmamış görünüyor {ISARET}",
                ["Durum dosyası (`durum` dalında `durum/son_calisma.json`) bulunamadı."])
    son_zaman = datetime.fromisoformat(son["son_basarili_calisma"])
    gun = (simdi - son_zaman).total_seconds() / 86400
    satirlar, baslik = [], None
    if gun > n["en_fazla_gun"]:
        baslik = f"Toplayıcı {int(gun)} gündür çalışmıyor {ISARET}"
        satirlar.append(f"Son başarılı çalışma: **{son_zaman:%d.%m.%Y %H:%M}** (Türkiye saati), {int(gun)} gün önce.")
    kotu = [(k, v) for k, v in (son.get("kaynaklar") or {}).items() if v.get("ardisik_hata", 0) >= n["ardisik_hata"]]
    for k, v in kotu:
        satirlar.append(f"- **{v.get('ad', k)}** {v['ardisik_hata']} çalışmadır üst üste okunamadı. Son hata: `{v.get('hata')}`")
    if kotu and not baslik:
        baslik = f"Toplayıcı: {len(kotu)} kaynak üst üste okunamıyor {ISARET}"
    return baslik, satirlar


def govde(satirlar: list[str]) -> str:
    return "\n".join([
        "Bu kayıt **nöbetçi** tarafından otomatik açıldı.", "", *satirlar, "",
        "## Ne yapmalısın?",
        "- Çoğu zaman bir şey yapman gerekmez: geçici bir site sorunuysa toplayıcı kendiliğinden düzelir ve bu kayıt "
        "otomatik kapanır.",
        "- Birkaç gün sürerse: **Actions** sekmesi → solda **Toplayıcı** → **Run workflow** ile elle çalıştır.",
        "- GitHub zamanlanmış iş akışını durdurduysa aynı sayfada **Enable workflow** düğmesi görünür; ona bas.",
        "- Bir kaynak kalıcı olarak değiştiyse Claude'dan okuyucuyu güncellemesini iste (ya da `toplayici/ayarlar.json`'da "
        "o kaynağı `\"acik\": false` yap).",
    ])


def gh(*komut) -> str:
    r = subprocess.run(["gh", *komut], capture_output=True, text=True, encoding="utf-8", timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    return r.stdout


def acik_kayit() -> dict | None:
    liste = json.loads(gh("issue", "list", "--state", "open", "--search", f"{ISARET} in:title", "--json", "number,title") or "[]")
    return next((i for i in liste if ISARET in i["title"]), None)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--durum", type=Path, required=True)
    p.add_argument("--kuru", action="store_true")
    a = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ayar = json.loads((BURASI / "ayarlar.json").read_text(encoding="utf-8"))
    try:
        son = json.loads(a.durum.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        son = None
    baslik, satirlar = sorunlar(son, datetime.now(TR), ayar)
    print(baslik or "Sorun yok.", *satirlar, sep="\n")
    if a.kuru:
        return 0
    kayit = acik_kayit()
    if baslik:
        metin = govde(satirlar)
        if kayit:
            if kayit["title"] != baslik:          # durum değişti: güncelle ve kısa yorumla haber ver
                gh("issue", "edit", str(kayit["number"]), "--title", baslik, "--body", metin)
                gh("issue", "comment", str(kayit["number"]), "--body", "Durum güncellendi: " + baslik.replace(ISARET, "").strip())
        else:
            gh("issue", "create", "--title", baslik, "--body", metin)
    elif kayit:
        gh("issue", "close", str(kayit["number"]), "--comment", "Toplayıcı yeniden düzenli çalışıyor; kayıt otomatik kapatıldı.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
