# Toplayıcı (Aşama 3)

Toplayıcı her sabah birkaç güvenilir kaynağa bakar. Bu yıl takvimden farklı bir şey görürse
sana bir **öneri** hazırlar. Kendisi hiçbir şeyi yayınlamaz, hiçbir öneriyi onaylamaz.
Mevsim takvimini de hiçbir zaman değiştirmez.

## Her sabah ne yapar?

Saat yaklaşık **06:30**'da (Türkiye saati) GitHub'ın sunucusunda kendiliğinden çalışır:

1. **İzmir halinin** sebze-meyve ve balık listelerini okur (son 4 gün; daha önce okuduğu günleri yeniden istemez).
2. **Hal Kayıt Sistemi**'nin (Ticaret Bakanlığı) ilk sayfasını ve **Konya halinin** son listesini okur.
3. **Resmî Gazete**'nin son 3 günlük fihristine bakar.
4. Listelerde yalnızca **hangi ürünlerin listelendiğini** kaydeder (fiyat kaydetmez; uygulamada fiyat yoktur).
5. Son haftaların kayıtlarını mevsim takvimiyle karşılaştırır. Aşağıdaki kurallardan biri tutarsa öneri açar.
6. Ne yaptığını `durum` dalındaki **DURUM.md** dosyasına yazar.

Çoğu gün hiçbir öneri çıkmaz. Bu normaldir; hata değildir.

## Öneri nasıl görünür?

Öneri, GitHub'da bir **Pull Request (PR)** olarak gelir: ürünün kartına eklenecek kısa bir
**"Bu yılın notu"** taslağı. Örnek (8 Mayıs 2026 sabahının gerçek İzmir hal kayıtlarından):

> **Erik İzmir halinde takvimden erken görüldü**
> Erik, 21 Nisan tarihinden bu yana İzmir halinde 13 pazar gününde listelendi. Takvimde Ege'deki hasat dönemi
> 1 Haziran tarihinde başlıyor. Bu, sezonun erken başladığını göstermez: ürün seradan, başka bölgeden,
> depodan ya da yurt dışından gelmiş olabilir.

PR açıklamasında şunlar yazar: ne görüldü (tarihler, kaç gün), takvimde ne yazıyor, bunun neden yalnızca bir
öneri olduğu, varsa ikinci kaynağın ne dediği, kaynak bağlantıları ve senin ne yapman gerektiği.
Not **bildirim göndermez**; yalnızca ürün kartında görünür.

Hal bir toptan piyasadır. Bir ürünün halde erken görünmesi sezonun kaydığını kanıtlamaz: ürün seradan,
başka bölgeden, depodan ya da yurt dışından gelebilir. Bu yüzden notlar yalnızca görüleni anlatır.

Resmî Gazete'de su ürünleri avcılığıyla ilgili bir başlık çıkarsa PR yerine bir **Issue** (yapılacak iş kaydı)
açılır: "Av kuralı değişmiş olabilir — takvimi gözden geçir". Toplayıcı metni yorumlamaz; bir insanın okuması gerekir.

## Senin ne yapman gerekiyor?

**Her gün hiçbir şey.** Öneriler sen bakana kadar bekler; o sürede uygulamaya hiçbir şey gitmez.

Bir öneriye baktığında:
- **Uygunsa:** PR sayfasında **Merge pull request** düğmesine bas. Not birkaç dakika içinde uygulamaya gider.
- **Uygun değilse:** **Close pull request** düğmesine bas. Aynı öneri bu sezon yeniden açılmaz.
- Metni değiştirmek istersen: **Files changed** → dosyanın sağındaki kalem simgesi.

Toplayıcı günde en fazla 2 öneri açar; fazlası kaybolmaz, sıraya alınır (`durum/bekleyen.json`) ve sonraki günlerde önce onlar açılır. Sırada beklerken notun geçerlilik süresi dolan öneri açılmaz; DURUM.md'de yazar.

## Elle çalıştırma

GitHub'da depo sayfası → **Actions** sekmesi → solda **Toplayıcı** → sağda **Run workflow** düğmesi.
- **Kuru çalıştırma** kutusunu işaretlersen: kaynakları okur ve raporlar ama öneri açmaz, hiçbir şey kaydetmez.
- **Yalnızca bu kaynak** listesinden tek bir kaynak seçebilirsin.

Sonuç, çalışmanın sayfasında **Summary** bölümünde Türkçe tablo olarak görünür.

Bilgisayarda (Claude için): depo klasöründe `python toplayici/toplayici.py --kuru`; örnek bir öneriyi görmek için
`python toplayici/toplayici.py --gosterim`; testler `python -m unittest discover -s toplayici/testler`.

## Durum nerede görünür?

Depo sayfasında dal seçiciden **durum** dalını seç → `durum/DURUM.md`. Orada son çalışmanın saati,
her kaynağın okunup okunmadığı, açılan öneriler ve eşleşmeyen hal adları yazar.
`durum/son_calisma.json` aynı bilginin makine okuyacağı halidir; `durum/gozlem/<yıl>.jsonl` günlük kayıtlar,
`durum/oneriler.json` açılmış önerilerin, `durum/bekleyen.json` sırada bekleyenlerin listesidir.

**Neden ayrı bir dal?** Uygulama yeni veriyi "veri sürümü" numarasından anlar; bu numara ana daldaki (main)
kayıt sayısıdır. Toplayıcı günlük durumunu main'e yazsaydı numara her sabah artar, yayın yeniden yapılır ve
telefonlar aynı veriyi boşuna yeniden indirirdi. Durum ayrı `durum` dalında tutulduğu için main'e yalnızca senin
onayladığın öneriler girer; veri sürümü yalnızca gerçek bir değişiklikte artar.

## Uyarı kaydı ("Toplayıcı N gündür çalışmıyor")

Her gün ayrıca **Nöbetçi** çalışır (yaklaşık 10:15). Şu durumlarda **tek bir** Issue açar; GitHub bunu sana
e-postayla bildirir:
- toplayıcı **3 günden uzun** süredir başarıyla çalışmadıysa,
- bir kaynak **5 çalışmadır üst üste** okunamadıysa.

Sorun geçince kayıt kendiliğinden kapanır. Çoğu zaman bir şey yapman gerekmez. Sürerse kayıttaki adımları izle
ya da Claude'dan bakmasını iste.

**60 gün kuralı:** GitHub, herkese açık depolarda 60 gün boyunca hiçbir etkinlik olmazsa zamanlanmış iş
akışlarını kendiliğinden durdurur (GitHub belgesi "Disabling and enabling a workflow"). Belge neyin "etkinlik"
sayıldığını yazmıyor. Önlem olarak (1) toplayıcı her gün `durum` dalına kayıt yazar, (2) Nöbetçi her gün
toplayıcıyı ve kendisini "etkin" duruma getirir. Bu ikisinin 60 gün sayacını sıfırladığı GitHub belgesinde
**doğrulanmadı**. Durdurulursa: Actions → iş akışı → **Enable workflow** düğmesi.

## Kurallar ve eşikler

Bütün sayılar `toplayici/ayarlar.json` dosyasındadır. "Pazar günü" halin liste yayımladığı gündür. Hafta sonu ve
bayramda boş gelen listeler ile bir önceki günün birebir aynısı olan (taşınmış) listeler sayılmaz.

| Kural | İzmir (Ege bölgesi / Ege Denizi) | Konya (İç Anadolu, yalnızca "pazarda yoğun" satırları) |
|---|---|---|
| **Halde göründü, takvimden erken** | Son 21 günde en az 4 pazar günü ve günlerin en az yarısında listelendi; takvim başlangıcına 10–90 gün var | Son 28 günde en az 4 gün ve %60; 14–90 gün var |
| **Sezon başladı ama halde yok** | Takvim 21+ gün önce başladı, o günden beri hiçbir adla listelenmedi (en az 6 pazar günü bakıldı) | 28+ gün, en az 6 liste |
| **Halden çekildi, takvim sürüyor** | Bu sezon en az 4 gün görüldü, son 8 pazar gününde hiç yok; takvimin bitmesine 21+ gün var | Son 6 liste; 28+ gün var |
| **Takvim bitti ama halde bol** | Takvim 14–60 gün önce bitti; son 21 günde en az 4 gün ve yarısında listelendi | 21–60 gün; %60 |

Sayılmayanlar:
- Adında ya da türünde **SERA, İTHAL, KÜLTÜR, DONUK, TATLI SU, YEM** geçen kalemler.
- Yılın neredeyse her günü halde olan kalemler (ör. sera domatesi, sivri biber): örneklem günlerinin %75'inde ya da
  daha fazlasında görülenler (Konya %80).
- Takvimde yıl boyu olan ürünler, yıl boyu çiftlik ürünleri, depodan bulunma dönemindeki ürünler.
- **Balıkta:** İzmir balık hali her denizden balık satar ve listesi denizi ayırmaz. Bu yüzden "erken" ve "uzadı"
  kuralları bir balık için yalnızca takvimde kaydı olan **hiçbir denizde** (Ege, Marmara, Karadeniz, Akdeniz) sezonda
  değilken çalışır; not metni de bunu söyler ("…hiçbir denizde av dönemi görünmediği hâlde…"). "Halde yok" ve
  "çekildi" kuralları Ege Denizi kaydına bakar ve metinde balığın başka denizlerden de gelebileceğini yazar.
- "Halde yok" ve "çekildi" kurallarında, ürünün **herhangi** bir kalemi (sera, ithal dahil) listedeyse öneri açılmaz.

**İkinci tanık** (tek başına öneri açmaz, yalnızca PR açıklamasına yazılır): Hal Kayıt Sistemi işlem hacmi
(son 7 kayıt, önceki 7 kayda göre %25'ten fazla artış/azalış) ve İzmir önerilerinde Konya'nın son 14 günü.

Her öneri ürün + kural + bölge + sezon yılı ile tek bir kimlik alır (ör. `erik_erken_ege_2026`). Aynı kimlikte
bir PR ya da Issue (açık ya da kapalı) varsa yeniden açılmaz.

## Ücret

**Ücretsiz.** GitHub Actions herkese açık depolarda ücretsizdir. Hesap, şifre, ücretli servis ya da yapay zekâ
kullanılmaz; yalnızca GitHub'ın her çalışmada kendiliğinden verdiği geçici izin kullanılır.

## Kaynaklar ve kullanım koşulları

| Kaynak | Ne alınır | Koşul / not |
|---|---|---|
| İzmir BB sebze-meyve hal bülteni (`openapi.izmir.bel.tr`) | Günlük liste | **CC BY 4.0**, atıf zorunlu (aşağıda) |
| İzmir BB balık hal bülteni | Günlük liste; DENİZ / KÜLTÜR / DONUK / İTHAL ayrımı | **CC BY 4.0** |
| Hal Kayıt Sistemi, Ticaret Bakanlığı (`hal.gov.tr`) | Yalnızca **ilk sayfa** (alfabetik ilk ~25 satır: acur, armut, asma yaprağı, avokado…), işlem hacmi | **Kullanım koşulları bulunamadı, doğrulanmadı.** Form gönderilmez, sonraki sayfalar okunmaz. Kapatmak için `ayarlar.json` → `hks` → `"acik": false` |
| Resmî Gazete günlük fihrist | Başlıklar | Kullanım koşulu bulunamadı; robots.txt genel okumayı yasaklamıyor |
| Konya BB hal listesi (`konya.bel.tr/hal-fiyatlari`) | Haftada 2 liste | Lisans belirsiz; robots.txt serbest |

Her kaynağa günde en fazla birkaç istek gider; istekler arasında 2 saniye beklenir. Tarım ve Orman Bakanlığı
(BSGM) sayfaları ve Meteoroloji (MGM) siteleri **okunmaz** (siteleri otomatik okumaya izin vermiyor ya da izin istiyor).

**Atıf:** Bu depodaki hal kaynaklı notlar İzmir Büyükşehir Belediyesi Açık Veri Portalı
(acikveri.bizizmir.com) verisinden, **CC BY 4.0** lisansıyla üretilir. Notların `kaynak_adi` alanında da yazar.

## Hal adı eşleştirmesi

`toplayici/eslestirme.json`: hal kalem adı → uygulamadaki ürün. Adlar karşılaştırılırken büyük-küçük harf,
fazla boşluk ve Türkçe harf farkları yok sayılır. Listede olmayan yeni bir ad görülürse DURUM.md'de
"eşleşmeyen ad" olarak yazar (hata değildir); Claude eşleştirmeye ekleyebilir.

## İleride eklenebilecek kaynaklar (şimdilik eklenmedi)

- **Ankara BB hali** (`ankara.bel.tr/hal-fiyatlari`): listeler sayfada düz okunabiliyor; İç Anadolu için ikinci kaynak olabilir.
- **Gaziantep, Malatya, Bursa** belediye hal sayfaları okunabiliyor; Güneydoğu, Doğu Anadolu ve Marmara için aday
  (Bursa'da balık bölge ayrımlı, ama son incelemede düzenli güncellenmiyordu).
- Lisans ve düzenlilik kontrol edilmeden eklenmeyecek.
