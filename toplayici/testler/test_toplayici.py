"""Toplayıcı testleri: ağ kullanmaz; kayıtlı örnek dosyalar (toplayici/ornekler) ve sentetik gözlemlerle çalışır.

  python -m unittest discover -s toplayici/testler -v
"""
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

BURASI = Path(__file__).resolve().parent
TOP = BURASI.parent
KOK = TOP.parent
sys.path.insert(0, str(TOP))
sys.path.insert(0, str(KOK / "araclar"))

import kaynaklar as K  # noqa: E402
import kurallar as R   # noqa: E402
import nobetci as N    # noqa: E402
import toplayici as T  # noqa: E402

ORNEK = TOP / "ornekler"
AYAR = json.loads((TOP / "ayarlar.json").read_text(encoding="utf-8"))
ESLER = R.eslestirme_yukle(TOP / "eslestirme.json", AYAR)
IZ = AYAR["kurallar"]["izmir"]


def oku(ad):
    return (ORNEK / ad).read_bytes()


def gunler(bas: date, bit: date, hafta_ici=True):
    g = bas
    while g <= bit:
        if not hafta_ici or g.weekday() < 5:
            yield g
        g += timedelta(days=1)


def kayitlar(bas, bit, adlar_fn, kaynak="izmir_sebze_meyve", hafta_sonu_bos=True):
    """Her hafta içi günü için ayrı (taşınmamış) bir liste; hafta sonları boş liste."""
    out = []
    for g in gunler(bas, bit, hafta_ici=False):
        if g.weekday() >= 5 and hafta_sonu_bos:
            out.append({"k": kaynak, "t": g.isoformat(), "bos": True})
            continue
        out.append({"k": kaynak, "t": g.isoformat(), "ozet": "o" + g.isoformat(), "adlar": sorted(adlar_fn(g))})
    return out


TEMEL = ["DOMATES SERA", "BIBER SIVRI", "LIMON LAMAS", "PATATES CALMA"]   # yıl boyu / sera kalemler


class TakvimYardim:
    @classmethod
    def setUpClass(cls):
        cls.takvim = R.takvim_yukle(KOK / "kaynak" / "urunler", "ege", "ege", IZ["donem_turleri"], AYAR["yil_boyu_takvim_gun"])


# --------------------------------------------------------------------------
class AyristiriciTestleri(unittest.TestCase):
    def test_izmir_sebze_meyve(self):
        g = K.izmir_ayristir("izmir_sebze_meyve", "2026-11-27", 200, oku("izmir_sebze_meyve_2026-11-27.json"))
        self.assertFalse(g.bos)
        self.assertGreater(len(g.adlar), 50)
        self.assertIn("ARMUT DEVECI", g.adlar)
        self.assertIn("ANANAS #ITHAL", g.adlar)          # MalTipAdi İTHAL etiketi korunur
        self.assertTrue(g.ozet)
        self.assertNotIn("OrtalamaUcret", json.dumps(g.kayit()))   # fiyat saklanmaz

    def test_izmir_balik(self):
        g = K.izmir_ayristir("izmir_balik", "2026-11-26", 200, oku("izmir_balik_2026-11-26.json"))
        self.assertIn("HAMSI (DENIZ)", g.adlar)
        self.assertTrue(any("KULTUR" in a for a in g.adlar))

    def test_izmir_bos_gun_ve_bozuk_yapi(self):
        self.assertTrue(K.izmir_ayristir("izmir_balik", "2026-11-28", 204, b"").bos)
        with self.assertRaises(K.KaynakHatasi):
            K.izmir_ayristir("izmir_balik", "2026-11-28", 200, b'{"Liste": []}')
        with self.assertRaises(K.KaynakHatasi):
            K.izmir_ayristir("izmir_balik", "2026-11-28", 500, b"")

    def test_izmir_eski_bulten_tasinmis_sayilir(self):
        govde = json.dumps({"BultenTarihi": "2026-11-26T00:00:00", "HalFiyatListesi": [{"MalAdi": "NAR", "MalTipAdi": "MEYVE"}]}).encode()
        g = K.izmir_ayristir("izmir_sebze_meyve", "2026-11-27", 200, govde)
        self.assertEqual(g.ek.get("bulten"), "2026-11-26")
        self.assertIn("2026-11-27", R.Gozlemler([g.kayit()]).tasindi)

    def test_konya(self):
        g = K.konya_ayristir(200, oku("konya_2026-11-26.html"))
        self.assertEqual(g.tarih, "2026-11-26")
        self.assertGreater(len(g.adlar), 80)
        self.assertIn("BIBER (SIVRI)", g.adlar)
        with self.assertRaises(K.KaynakHatasi):
            K.konya_ayristir(200, b"<html>bakim calismasi</html>")

    def test_hks_ilk_sayfa(self):
        g = K.hks_ayristir(200, oku("hks_ilk_sayfa.html"))
        self.assertEqual(g.tarih, "2026-11-27")
        self.assertGreater(g.ek["hacim"]["ARMUT"], 1000)
        with self.assertRaises(K.KaynakHatasi):
            K.hks_ayristir(200, b"<html></html>")

    def test_resmi_gazete_windows_1254_ve_anahtar_kelime(self):
        kal = AYAR["resmi_gazete"]["anahtar_kaliplar"]
        b = K.rg_ayristir(date(2026, 9, 16), 200, oku("resmi_gazete_20260916.htm"))
        es = K.rg_eslesenler(b, kal)
        self.assertEqual(len(es), 2)
        self.assertTrue(all("Su Ürünleri Avcılığının" in e["baslik"] for e in es))   # Türkçe harfler doğru çözüldü
        self.assertTrue(es[0]["link"].startswith("https://www.resmigazete.gov.tr/eskiler/2026/09/20260916-"))
        b2 = K.rg_ayristir(date(2026, 11, 27), 200, oku("resmi_gazete_20261127.htm"))
        self.assertGreater(len(b2), 20)
        self.assertEqual(K.rg_eslesenler(b2, kal), [])        # tarih içindeki "4/6/2026" eşleşmez
        self.assertEqual(K.rg_eslesenler([{"baslik": "Türk Gıda Kodeksi Tebliği (Tebliğ No: 2026/19)", "link": ""}], kal), [])


# --------------------------------------------------------------------------
class EslestirmeTestleri(unittest.TestCase):
    def test_normallestirme(self):
        self.assertEqual(K.normal("ARMUT  DEVECI"), "ARMUT DEVECI")
        self.assertEqual(K.normal("Armut Deveci "), "ARMUT DEVECI")
        self.assertEqual(K.normal("ARMUT DEVECİ"), "ARMUT DEVECI")
        self.assertEqual(K.normal("LEVREK ( KÜLTÜR )"), "LEVREK (KULTUR)")
        self.assertEqual(K.normal("AHTAPOT(DONUK)"), "AHTAPOT (DONUK)")
        self.assertEqual(K.normal("şeftalı"), "SEFTALI")

    def test_etiketler(self):
        self.assertEqual(K.etiketler("DOMATES SERA"), {"SERA"})
        self.assertEqual(K.etiketler("BIBER KIRMIZI (TARLA)"), {"TARLA"})
        self.assertEqual(K.etiketler("ANANAS #ITHAL"), {"ITHAL"})

    def test_esleme_ve_dislama(self):
        es = ESLER["izmir_sebze_meyve"]
        self.assertEqual(es.bul("ARMUT DEVECI").urun_id, "armut")
        self.assertEqual(es.bul(K.normal("KİRAZ  ")).urun_id, "kiraz")
        self.assertIsNone(es.sinyal_kalemi("DOMATES SERA"))           # sera
        self.assertIsNone(es.sinyal_kalemi("KIVI ITHAL #ITHAL"))      # ithal
        self.assertIsNone(es.sinyal_kalemi("BIBER SIVRI"))            # yıl boyu halde
        self.assertEqual(es.sinyal_kalemi("KIRAZ").urun_id, "kiraz")
        self.assertIsNone(ESLER["izmir_balik"].sinyal_kalemi("LEVREK (KULTUR) #KULTUR"))
        self.assertIsNone(ESLER["izmir_balik"].sinyal_kalemi("DONUK HAMSI"))

    def test_eslesmeyen_adlar_listelenir(self):
        es = ESLER["izmir_sebze_meyve"]
        self.assertEqual(es.eslesmeyenler(["ARMUT DEVECI", "ANANAS #ITHAL", "YENI MEYVE"]), ["YENI MEYVE"])

    def test_tum_urun_kimlikleri_var(self):
        var = {p.stem for p in (KOK / "kaynak" / "urunler").glob("*.json")}
        for ad, es in ESLER.items():
            for k in es.kalemler.values():
                self.assertIn(k.urun_id, var, f"{ad}: {k.ad}")

    def test_ornek_listelerin_hepsi_eslesiyor(self):
        for ad, dosya, t in (("izmir_sebze_meyve", "izmir_sebze_meyve_2026-11-27.json", "2026-11-27"),
                             ("izmir_balik", "izmir_balik_2026-11-26.json", "2026-11-26")):
            g = K.izmir_ayristir(ad, t, 200, oku(dosya))
            self.assertEqual(ESLER[ad].eslesmeyenler(g.adlar), [], ad)


# --------------------------------------------------------------------------
class KuralTestleri(TakvimYardim, unittest.TestCase):
    es = ESLER["izmir_sebze_meyve"]

    def calis(self, kay, bugun, es=None, ay=IZ, takvim=None):
        return R.degerlendir(R.Gozlemler(kay), es or self.es, takvim or self.takvim, bugun, ay)

    def test_erken_gorunme(self):
        # Ege kiraz hasadı 24 Nisan'da başlar; 1 Nisan'dan beri her gün halde -> öneri
        kay = kayitlar(date(2027, 3, 15), date(2027, 4, 12),
                       lambda g: TEMEL + (["KIRAZ"] if g >= date(2027, 4, 1) else []))
        s = [x for x in self.calis(kay, date(2027, 4, 12)) if x.urun_id == "kiraz"]
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0].kural, "erken")
        self.assertEqual(s[0].sezon_bas, date(2027, 4, 24))
        self.assertEqual(s[0].ilk, "2027-04-01")

    def test_erken_sera_ve_ithal_sayilmaz(self):
        kay = kayitlar(date(2027, 3, 15), date(2027, 4, 12), lambda g: TEMEL + ["KIRAZ SERA", "KIRAZ #ITHAL"])
        self.assertFalse([x for x in self.calis(kay, date(2027, 4, 12)) if x.urun_id == "kiraz"])

    def test_erken_sezona_cok_yakinsa_oneri_yok(self):
        kay = kayitlar(date(2027, 3, 25), date(2027, 4, 20), lambda g: TEMEL + ["KIRAZ"])
        self.assertFalse([x for x in self.calis(kay, date(2027, 4, 20)) if x.urun_id == "kiraz"])   # 4 gün kala

    def test_tasinmis_listeler_sayilmaz(self):
        # Kiraz yalnızca bir gün yeni listede; sonraki günler aynı listenin tekrarı (taşınmış)
        kay = kayitlar(date(2027, 3, 15), date(2027, 4, 7), lambda g: TEMEL)
        for g in gunler(date(2027, 4, 8), date(2027, 4, 14)):
            kay.append({"k": "izmir_sebze_meyve", "t": g.isoformat(), "ozet": "ayni", "adlar": TEMEL + ["KIRAZ"]})
        gz = R.Gozlemler(kay)
        self.assertEqual(len(gz.tasindi), 4)
        self.assertFalse([x for x in self.calis(kay, date(2027, 4, 14)) if x.urun_id == "kiraz"])

    def test_hafta_sonu_bosluklari_sinyal_degildir(self):
        # Yalnızca hafta sonları (boş liste) var: pazar günü yok -> hiçbir kural çalışmaz
        kay = [{"k": "izmir_sebze_meyve", "t": g.isoformat(), "bos": True}
               for g in gunler(date(2027, 5, 1), date(2027, 6, 30), hafta_ici=False) if g.weekday() >= 5]
        self.assertEqual(self.calis(kay, date(2027, 6, 30)), [])

    def test_sezon_basladi_halde_yok(self):
        # Ege bezelye 16 Mart'ta başlar; 1 Mart'tan beri listede hiç yok -> öneri
        kay = kayitlar(date(2027, 3, 1), date(2027, 4, 15), lambda g: TEMEL)
        s = [x for x in self.calis(kay, date(2027, 4, 15)) if x.urun_id == "bezelye"]
        self.assertEqual([x.kural for x in s], ["yok"])

    def test_yok_kurali_sera_kalemi_varsa_calismaz(self):
        # Tarla domatesi (temmuz) yok ama sera domatesi her gün var -> "halde yok" denmez
        kay = kayitlar(date(2027, 7, 1), date(2027, 8, 15), lambda g: TEMEL)
        self.assertFalse([x for x in self.calis(kay, date(2027, 8, 15)) if x.urun_id == "domates"])

    def test_yok_kurali_yeterli_pazar_gunu_ister(self):
        kay = kayitlar(date(2027, 4, 12), date(2027, 4, 15), lambda g: TEMEL)     # yalnızca 4 pazar günü
        self.assertFalse([x for x in self.calis(kay, date(2027, 4, 15)) if x.urun_id == "bezelye"])

    def test_halden_cekildi(self):
        # Kiraz 24 Nisan – 31 Temmuz; mayısta var, 1 Haziran'dan sonra yok
        kay = kayitlar(date(2027, 4, 24), date(2027, 6, 20),
                       lambda g: TEMEL + (["KIRAZ"] if g < date(2027, 6, 1) else []))
        s = [x for x in self.calis(kay, date(2027, 6, 20)) if x.urun_id == "kiraz"]
        self.assertEqual([x.kural for x in s], ["cekildi"])
        self.assertEqual(s[0].son, "2027-05-31")

    def test_takvim_bitti_halde_bol(self):
        # Bezelye 31 Mayıs'ta biter; haziran boyunca halde
        kay = kayitlar(date(2027, 5, 20), date(2027, 6, 25), lambda g: TEMEL + ["BEZELYE"])
        s = [x for x in self.calis(kay, date(2027, 6, 25)) if x.urun_id == "bezelye"]
        self.assertEqual([x.kural for x in s], ["uzadi"])

    def test_depo_donemi_sinyal_uretmez(self):
        t = R.UrunTakvimi("nar", "Nar")
        t.sezon.append(R.Satir("nar", "bolge", "ege", "hasat", "09-01", "10-31", "k", None, "resmi"))
        t.depo.append(R.Satir("nar", "bolge", "ege", "depo", "11-01", "04-15", "k", None, "resmi"))
        es = R.Eslestirme({"orneklem_gun_sayisi": 0, "kalemler": [{"ad": "NAR", "urun_id": "nar"}]}, 0.75, [])
        kay = kayitlar(date(2027, 1, 1), date(2027, 1, 31), lambda g: ["NAR"])
        self.assertEqual(self.calis(kay, date(2027, 1, 31), es=es, takvim={"nar": t}), [])

    def test_yil_boyu_ve_ciftlik_urunleri_takvimde_yok(self):
        self.assertNotIn("cipura_ciftlik", self.takvim)        # çiftlik, yıl boyu
        self.assertNotIn("maydanoz", self.takvim)              # 01-01 – 12-31 satırı
        self.assertIn("kiraz", self.takvim)

    def test_balik_deniz_kaydi(self):
        es = ESLER["izmir_balik"]
        # Ege hamsi avı 1 Eylül'de açılır; ağustos ortasından beri DENİZ etiketli hamsi -> erken
        kay = kayitlar(date(2027, 7, 25), date(2027, 8, 20), lambda g: ["CIPURA (KULTUR) #KULTUR"] +
                       (["HAMSI (DENIZ)"] if g >= date(2027, 8, 9) else []), kaynak="izmir_balik")
        s = [x for x in self.calis(kay, date(2027, 8, 20), es=es) if x.urun_id == "hamsi"]
        self.assertEqual([x.kural for x in s], ["erken"])
        self.assertEqual(s[0].satir.kapsam_turu, "deniz")
        # Donuk hamsi sayılmaz
        kay2 = kayitlar(date(2027, 7, 25), date(2027, 8, 20), lambda g: ["DONUK HAMSI"], kaynak="izmir_balik")
        self.assertFalse([x for x in self.calis(kay2, date(2027, 8, 20), es=es) if x.urun_id == "hamsi"])

    def test_balik_baska_denizde_sezondaysa_sinyal_yok(self):
        # Hamsi: Ege dönemi bitmiş, Karadeniz dönemi sürüyor -> halde görünmesi sinyal değildir
        t = R.UrunTakvimi("hamsi", "Hamsi")
        t.sezon.append(R.Satir("hamsi", "deniz", "ege", "av", "09-01", "01-31", "k", None, "akademik"))
        t.baska.append(R.Satir("hamsi", "deniz", "karadeniz", "av", "10-15", "03-31", "k", None, "akademik"))
        kay = kayitlar(date(2027, 2, 10), date(2027, 3, 10), lambda g: ["HAMSI (DENIZ)"], kaynak="izmir_balik")
        es = ESLER["izmir_balik"]
        self.assertEqual(self.calis(kay, date(2027, 3, 10), es=es, takvim={"hamsi": t}), [])
        t.baska.clear()                              # Karadeniz kaydı olmasaydı "uzadı" olurdu
        self.assertEqual([x.kural for x in self.calis(kay, date(2027, 3, 10), es=es, takvim={"hamsi": t})], ["uzadi"])

    def test_balik_hicbir_denizde_sezonda_degilse_sinyal(self):
        # Gerçek takvim: hamsi Ege 1 Eylül – 31 Mart; Marmara ve Karadeniz daha önce biter -> nisan sonunda hiçbir denizde yok
        tk = self.takvim
        self.assertTrue({x.kapsam_id for x in tk["hamsi"].baska} >= {"karadeniz", "marmara"})
        es = ESLER["izmir_balik"]
        kay = kayitlar(date(2027, 4, 1), date(2027, 4, 28), lambda g: ["HAMSI (DENIZ)"], kaynak="izmir_balik")
        s = [x for x in self.calis(kay, date(2027, 4, 28), es=es) if x.urun_id == "hamsi"]
        self.assertEqual([x.kural for x in s], ["uzadi"])
        self.assertIn("hiçbir denizde av dönemi görünmediği hâlde", T.not_olustur(s[0], "izmir_balik", IZ)["metin"])
        # Mercan: Ege dönemi 31 Mart'ta biter ama Akdeniz 14 Nisan'a kadar sürer -> 10 Nisan'da sinyal yok
        kay2 = kayitlar(date(2027, 3, 15), date(2027, 4, 10), lambda g: ["MERCAN (KUCUK BOY)"], kaynak="izmir_balik")
        self.assertFalse([x for x in self.calis(kay2, date(2027, 4, 10), es=es) if x.urun_id == "mercan"])

    def test_balik_yok_notu_baska_denizleri_soyler(self):
        kay = kayitlar(date(2027, 9, 1), date(2027, 10, 10), lambda g: ["CIPURA (KULTUR) #KULTUR"], kaynak="izmir_balik")
        s = [x for x in self.calis(kay, date(2027, 10, 10), es=ESLER["izmir_balik"]) if x.urun_id == "lufer"]
        self.assertEqual([x.kural for x in s], ["yok"])
        self.assertIn("başka denizlerden de balık gelir", T.not_olustur(s[0], "izmir_balik", IZ)["metin"])

    def test_hks_egilimi(self):
        es = ESLER["hks"]
        kay = [{"k": "hks", "t": (date(2027, 8, 1) + timedelta(days=i)).isoformat(),
                "hacim": {"ARMUT": 1000 if i < 7 else 2000}} for i in range(14)]
        e = R.hks_egilimi(kay, es, "armut", 7, 0.25)
        self.assertEqual((e["yon"], e["degisim"]), ("artiyor", 100))
        self.assertIsNone(R.hks_egilimi(kay, es, "kiraz", 7, 0.25))


# --------------------------------------------------------------------------
class SahteGitHub:
    def __init__(self, onceden=()):
        self.prler, self.issuelar, self.onceden = [], [], set(onceden)

    def onceden_var_mi(self, kimlik):
        return kimlik in self.onceden

    def pr_ac(self, kimlik, yol, icerik, baslik, govde_uret):
        self.prler.append((kimlik, yol, icerik, govde_uret("kontrol")))
        return 100 + len(self.prler)

    def issue_ac(self, baslik, govde):
        self.issuelar.append((baslik, govde))
        return 200 + len(self.issuelar)


def sahte_indir(hata_kaynagi=None):
    def indir(url, ayar):
        if hata_kaynagi and hata_kaynagi in url:
            raise TimeoutError("zaman aşımı")
        if "sebzemeyve/2026-11-27" in url:
            return K.Yanit(url, 200, oku("izmir_sebze_meyve_2026-11-27.json"))
        if "balik/2026-11-26" in url:
            return K.Yanit(url, 200, oku("izmir_balik_2026-11-26.json"))
        if "openapi.izmir" in url:
            return K.Yanit(url, 204, b"")
        if "konya" in url:
            return K.Yanit(url, 200, oku("konya_2026-11-26.html"))
        if "hal.gov.tr" in url:
            return K.Yanit(url, 200, oku("hks_ilk_sayfa.html"))
        if "20260916" in url:
            return K.Yanit(url, 200, oku("resmi_gazete_20260916.htm"))
        if "resmigazete" in url:            # diğer günler: 27.11.2026 fihristi o günün tarihiyle
            gun = url.rsplit("/", 1)[-1][:8]
            return K.Yanit(url, 200, oku("resmi_gazete_20261127.htm").replace(b"20261127", gun.encode()))
        return K.Yanit(url, 404, b"")
    return indir


class AkisTestleri(unittest.TestCase):
    def setUp(self):
        self.gecici = Path(tempfile.mkdtemp())
        self.durum = self.gecici / "durum"
        self.ayar = json.loads((TOP / "ayarlar.json").read_text(encoding="utf-8"))
        self.ayar["istek"]["istekler_arasi_bekleme_sn"] = 0
        self.ayar_yolu = self.gecici / "ayarlar.json"
        self.ayar_yolu.write_text(json.dumps(self.ayar, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.gecici, ignore_errors=True)

    def calis(self, bugun=date(2026, 11, 27), indir=None, gh=None, kuru=False, tek=None, en_fazla=50):
        return T.calistir(self.durum, kuru, tek, bugun, indir=indir or sahte_indir(), github=gh or SahteGitHub(),
                          ayar_yolu=self.ayar_yolu, cikti=lambda *a: None, en_fazla=en_fazla)

    def test_bir_kaynak_cokse_digerleri_devam_eder(self):
        r = self.calis(indir=sahte_indir(hata_kaynagi="hal.gov.tr"))
        k = r["kaynaklar"]
        self.assertEqual(k["hks"]["durum"], "hata")
        self.assertIn("zaman aşımı", k["hks"]["hata"])
        self.assertEqual(k["hks"]["ardisik_hata"], 1)
        for ad in ("izmir_sebze_meyve", "izmir_balik", "konya", "resmi_gazete"):
            self.assertEqual(k[ad]["durum"], "basarili", ad)
        son = json.loads((self.durum / "son_calisma.json").read_text(encoding="utf-8"))
        self.assertTrue(son["son_basarili_calisma"])
        self.assertTrue((self.durum / "DURUM.md").exists())
        self.assertTrue(list((self.durum / "gozlem").glob("2026.jsonl")))
        r2 = self.calis(bugun=date(2026, 11, 28), indir=sahte_indir(hata_kaynagi="hal.gov.tr"))
        self.assertEqual(r2["kaynaklar"]["hks"]["ardisik_hata"], 2)

    def test_degisiklik_yoksa_oneri_yok_ve_bugunun_bos_listesi_saklanmaz(self):
        gh = SahteGitHub()
        r = self.calis(gh=gh)
        self.assertEqual(gh.prler, [])
        kay = [json.loads(s) for s in (self.durum / "gozlem" / "2026.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertFalse(any(x["k"] == "izmir_balik" and x["t"] == "2026-11-27" for x in kay))   # bugün boş: yarın yeniden
        self.assertTrue(any(x["k"] == "izmir_balik" and x["t"] == "2026-11-26" and not x.get("bos") for x in kay))
        self.assertIn("yeni bir işaret yok", T.durum_md(r))

    def test_kuru_calistirma_hicbir_sey_yazmaz(self):
        gh = SahteGitHub()
        self.calis(kuru=True, gh=gh)
        self.assertFalse(self.durum.exists())
        self.assertEqual(gh.prler, [])

    def test_resmi_gazete_issue_ve_tekrar_acilmaz(self):
        gh = SahteGitHub()
        self.calis(bugun=date(2026, 9, 17), gh=gh, tek="resmi_gazete")
        self.assertEqual(len(gh.issuelar), 1)
        self.assertIn("Av kuralı değişmiş olabilir — takvimi gözden geçir", gh.issuelar[0][0])
        self.assertIn("[rg_20260916]", gh.issuelar[0][0])
        self.assertIn("20260916-4.pdf", gh.issuelar[0][1])
        # Aynı gün yeniden çalışınca: bakılmış gün tekrar istenmez, issue tekrar açılmaz
        self.calis(bugun=date(2026, 9, 17), gh=gh, tek="resmi_gazete")
        self.assertEqual(len(gh.issuelar), 1)

    def _kiraz_gozlemi(self):
        kay = kayitlar(date(2027, 3, 15), date(2027, 4, 12), lambda g: TEMEL + (["KIRAZ"] if g >= date(2027, 4, 1) else []))
        (self.durum / "gozlem").mkdir(parents=True, exist_ok=True)
        (self.durum / "gozlem" / "2027.jsonl").write_text("\n".join(json.dumps(x) for x in kay) + "\n", encoding="utf-8")

    def test_oneri_pr_ve_tekrar_acilmaz(self):
        self._kiraz_gozlemi()
        gh = SahteGitHub()
        self.calis(bugun=date(2027, 4, 12), gh=gh, tek="yok")
        kimlikler = [p[0] for p in gh.prler]
        self.assertIn("kiraz_erken_ege_2027", kimlikler)
        kimlik, yol, icerik, govde = next(p for p in gh.prler if p[0] == "kiraz_erken_ege_2027")
        self.assertEqual(yol, "kaynak/notlar/2027/kiraz_erken_ege_2027.json")
        self.assertFalse(icerik["bildirimde_goster"])
        self.assertIn("CC BY 4.0", icerik["kaynak_adi"])
        for bolum in ("## Ne görüldü", "## Takvimde ne yazıyor", "## Bu neden yalnızca bir öneri?", "## Kaynaklar", "## Ne yapmalısın?"):
            self.assertIn(bolum, govde)
        once = len(gh.prler)
        self.calis(bugun=date(2027, 4, 13), gh=gh, tek="yok")      # ertesi gün: aynı öneri yeniden açılmaz
        self.assertEqual([p[0] for p in gh.prler[once:]].count("kiraz_erken_ege_2027"), 0)

    def test_github_ta_onceden_varsa_acilmaz(self):
        self._kiraz_gozlemi()
        gh = SahteGitHub(onceden={"kiraz_erken_ege_2027"})
        r = self.calis(bugun=date(2027, 4, 12), gh=gh, tek="yok")
        self.assertNotIn("kiraz_erken_ege_2027", [p[0] for p in gh.prler])
        self.assertIn("kiraz_erken_ege_2027", r["oneriler"]["zaten_var"])

    def test_gunluk_oneri_siniri(self):
        self._kiraz_gozlemi()
        gh = SahteGitHub()
        r = T.calistir(self.durum, False, "yok", date(2027, 4, 12), indir=None, github=gh, ayar_yolu=self.ayar_yolu,
                       cikti=lambda *a: None, en_fazla=0)
        self.assertEqual(gh.prler, [])
        self.assertIn("kiraz_erken_ege_2027", r["oneriler"]["ertelendi"])
        sira = json.loads((self.durum / "bekleyen.json").read_text(encoding="utf-8"))
        self.assertIn("kiraz_erken_ege_2027", sira)
        # Ertesi gün işaret artık görünmese bile (gözlemler silindi) sıradaki öneri kaybolmaz, açılır
        shutil.rmtree(self.durum / "gozlem")
        self.calis(bugun=date(2027, 4, 13), gh=gh, tek="yok")
        self.assertIn("kiraz_erken_ege_2027", [p[0] for p in gh.prler])
        self.assertNotIn("kiraz_erken_ege_2027", json.loads((self.durum / "bekleyen.json").read_text(encoding="utf-8")))

    def test_suresi_dolan_sira_dusurulur(self):
        self._kiraz_gozlemi()
        T.calistir(self.durum, False, "yok", date(2027, 4, 12), indir=None, github=SahteGitHub(), ayar_yolu=self.ayar_yolu,
                   cikti=lambda *a: None, en_fazla=0)
        shutil.rmtree(self.durum / "gozlem")
        gh = SahteGitHub()
        r = self.calis(bugun=date(2027, 5, 20), gh=gh, tek="yok")
        self.assertIn("kiraz_erken_ege_2027", r["oneriler"]["suresi_doldu"])
        self.assertNotIn("kiraz_erken_ege_2027", [p[0] for p in gh.prler])      # süresi geçen öneri açılmaz

    def test_not_dosyasi_derle_dogrulamasindan_gecer(self):
        self._kiraz_gozlemi()
        gh = SahteGitHub()
        self.calis(bugun=date(2027, 4, 12), gh=gh, tek="yok")
        self.assertTrue(gh.prler)
        kaynak = self.gecici / "kaynak"
        shutil.copytree(KOK / "kaynak", kaynak)
        for _, yol, icerik, _ in gh.prler:
            T.json_yaz(self.gecici / yol, icerik)
            import derle
            for alan in ("baslik", "metin", "kaynak_adi"):
                self.assertFalse(derle._fiyat_dili(icerik[alan]), icerik[alan])
        ok, metin = T.derle_kontrol(kaynak)
        self.assertTrue(ok, metin)

    def test_gosterim(self):
        satirlar = []
        r = T.gosterim(cikti=satirlar.append)
        self.assertEqual(len(r["oneriler"]["kuru_gosterilen"]), 1)
        self.assertTrue(any("=== KURU: açılacak PR ===" in s for s in satirlar))


# --------------------------------------------------------------------------
class NobetciTestleri(unittest.TestCase):
    simdi = datetime.fromisoformat("2026-12-10T10:15:00+03:00")

    def test_uzun_suredir_calismadi(self):
        b, s = N.sorunlar({"son_basarili_calisma": "2026-12-05T06:31:00+03:00", "kaynaklar": {}}, self.simdi, AYAR)
        self.assertIn("5 gündür çalışmıyor", b)

    def test_her_sey_yolunda(self):
        b, s = N.sorunlar({"son_basarili_calisma": "2026-12-10T06:31:00+03:00", "kaynaklar": {"hks": {"ardisik_hata": 4}}},
                          self.simdi, AYAR)
        self.assertIsNone(b)

    def test_kaynak_ust_uste_hata(self):
        b, s = N.sorunlar({"son_basarili_calisma": "2026-12-10T06:31:00+03:00",
                           "kaynaklar": {"hks": {"ad": "HKS", "ardisik_hata": 5, "hata": "HTTP 403"}}}, self.simdi, AYAR)
        self.assertIn("üst üste okunamıyor", b)
        self.assertTrue(any("HTTP 403" in x for x in s))

    def test_durum_dosyasi_yok(self):
        b, _ = N.sorunlar(None, self.simdi, AYAR)
        self.assertIn("hiç çalışmamış", b)


if __name__ == "__main__":
    unittest.main()
