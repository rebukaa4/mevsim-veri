# Mevsim verisi

Türkiye'de meyve, sebze, ot, balık ve deniz ürünlerinin **bölgelere ve denizlere göre
mevsim takvimi**; ürün başına seçme ipuçları, hazırlama adımları ve tarifler.
Bu depo, "Mevsim" mobil uygulamasının indirdiği veri dosyasını üretir.

> **Durum:** Yedi bölgenin hepsi (355 ürün; Ege Denizi, Akdeniz, Marmara Denizi ve Karadeniz balıkları ile Van Gölü'nün
> inci kefali dahil).

## Yapı

- `kaynak/` — düzenlenen dosyalar (ürün başına bir dosya: `kaynak/urunler/<urun_id>.json`)
- `sema/v1.schema.json` — yayın dosyasının biçimi
- `araclar/derle.py` — doğrulama ve derleme (`python araclar/derle.py`)
- `araclar/icerik_aktar.py` — ürün ve tarif dosyalarını uygulama klasöründeki onaylı taslaklardan yeniden üretir
  (`python araclar/icerik_aktar.py --girdi ../mevsim_app`); sezon satırları ve kaynakları bölge başına
  `araclar/mevsim/<bolge_id>.json` (ör. `ege.json`, `akdeniz.json`, `marmara.json`, `karadeniz.json`). Bir bölge dosyası yalnızca o bölgeyi ve
  kıyısındaki denizi kapsar; deniz balıkları yalnızca deniz kaydı alır. İç su (göl) balığı `ic_su_adi` taşır (ör. inci kefali: "Van Gölü"),
  deniz kaydı almaz, il kaydı alır. Çiftlik ürünü yıl boyudur; yalnızca `"yil_boyu": false` yazılan çiftlik ürünü (Türk somonu) hasat kaydı alır.
- `toplayici/` — her sabah hal ve Resmî Gazete kaynaklarını tarayıp **öneri** (PR / Issue) açan program; ayrıntı `toplayici/README.md`.
  Günlük durumu ayrı `durum` dalında tutar (main ve veri sürümü değişmez).
- `testler/` — derleyici testleri (kendi örnek kayıtlarıyla, `testler/ornek_kaynak/`) (`python -m unittest discover -s testler`)
- Yayın adresi: `https://rebukaa4.github.io/mevsim-veri/v1/surum.json` ve `.../v1/mevsim_veri.json`

Her değişiklik bir Pull Request ile önerilir ve onaylanmadan yayınlanmaz.

## Tanınırlık sırası

Uygulama, bir kategorideki ürünleri alfabeye göre değil, Batı Türkiye'de sıradan bir evin
ne kadar sık alıp yediğine göre sıralar. Sıra `araclar/bilinirlik.json` dosyasında elle tutulur:
her ürüne 1–5 arası `bilinirlik` (1 = herkes düzenli alır, ör. domates, hamsi, elma;
3 = bilinir ama ara sıra alınır; 5 = nadir / uzman işi, ör. akivades, cibez) verilir, liste sırası da
`siralama` olur. "Az bilinen" işaretli ürünler en az 3 olur; yöresel ürünler ana ürünlerinin
düzeyini alır ama o düzeydeki genel ürünlerin arkasına yazılır. İzmir hal kayıtlarındaki bulunma
oranına yalnızca sağlama için bakıldı; sıra bir değerlendirmedir, PR ile önerilip düzeltilebilir.

## Kaynak ve lisans

Her mevsim kaydında kaynak adı, bağlantısı ve araştırma tarihi bulunur.
Verinin kullanım lisansı henüz belirlenmedi (yer tutucu).
