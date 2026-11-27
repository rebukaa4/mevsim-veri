# Mevsim verisi

Türkiye'de meyve, sebze, ot, balık ve deniz ürünlerinin **bölgelere ve denizlere göre
mevsim takvimi**; ürün başına seçme ipuçları, hazırlama adımları ve tarifler.
Bu depo, "Mevsim" mobil uygulamasının indirdiği veri dosyasını üretir.

> **Durum:** Ege bölgesi ilk veri seti (153 ürün, Ege Denizi balıkları dahil). Diğer bölgeler
> sonraki aşamalarda eklenecek.

## Yapı

- `kaynak/` — düzenlenen dosyalar (ürün başına bir dosya: `kaynak/urunler/<urun_id>.json`)
- `sema/v1.schema.json` — yayın dosyasının biçimi
- `araclar/derle.py` — doğrulama ve derleme (`python araclar/derle.py`)
- `araclar/ege_icerik_aktar.py` — Ege ilk verisini uygulama klasöründeki onaylı taslaklardan yeniden üretir
  (`python araclar/ege_icerik_aktar.py --girdi ../mevsim_app`); sezon satırları ve kaynak listesi `araclar/ege_mevsim.json`
- `testler/` — derleyici testleri (kendi örnek kayıtlarıyla, `testler/ornek_kaynak/`) (`python -m unittest discover -s testler`)
- Yayın adresi: `https://rebukaa4.github.io/mevsim-veri/v1/surum.json` ve `.../v1/mevsim_veri.json`

Her değişiklik bir Pull Request ile önerilir ve onaylanmadan yayınlanmaz.

## Kaynak ve lisans

Her mevsim kaydında kaynak adı, bağlantısı ve araştırma tarihi bulunur.
Verinin kullanım lisansı henüz belirlenmedi (yer tutucu).
