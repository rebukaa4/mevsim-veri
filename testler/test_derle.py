"""derle.py birim testleri. Çalıştırma: python -m unittest discover -s testler -v"""
import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "araclar"))
import derle  # noqa: E402

SEMA = KOK / "sema" / "v1.schema.json"
ORNEK = KOK / "testler" / "ornek_kaynak"


def mevsim(mid, tur="bolge", kid="ege", donem="hasat", bas="03-01", bit="05-31"):
    return {"id": mid, "kapsam_turu": tur, "kapsam_id": kid, "donem_turu": donem, "bas": bas, "bit": bit,
            "kaynak_adi": "Test kaynağı", "arastirma_tarihi": "2026-11-27", "guven": "tahmini"}


class DerleTesti(unittest.TestCase):
    def setUp(self):
        self.gecici = Path(tempfile.mkdtemp())
        self.kaynak = self.gecici / "kaynak"
        # Testler gerçek veriye değil, kendi örnek kayıtlarına dayanır; ortak tablolar gerçek dosyalardan gelir.
        shutil.copytree(KOK / "kaynak" / "ortak", self.kaynak / "ortak")
        for klasor in ("urunler", "tarifler"):
            shutil.copytree(ORNEK / klasor, self.kaynak / klasor)
        (self.kaynak / "notlar").mkdir()
        (self.kaynak / "gorseller.json").write_text("[]", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.gecici, ignore_errors=True)

    # yardımcılar ---------------------------------------------------------
    def urun_yaz(self, urun):
        (self.kaynak / "urunler" / f"{urun['id']}.json").write_text(json.dumps(urun, ensure_ascii=False), encoding="utf-8")

    def urun_oku(self, uid):
        return json.loads((self.kaynak / "urunler" / f"{uid}.json").read_text(encoding="utf-8"))

    def urun_degistir(self, uid, fn):
        u = self.urun_oku(uid)
        fn(u)
        self.urun_yaz(u)

    def ortak_degistir(self, dosya, fn):
        yol = self.kaynak / "ortak" / dosya
        v = json.loads(yol.read_text(encoding="utf-8"))
        v = fn(v) or v
        yol.write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")

    def derle(self, onceki=None, veri_surumu=5):
        return derle.derle(self.kaynak, SEMA, veri_surumu, onceki)

    def reddedilmeli(self, parca):
        _, hatalar, _ = self.derle()
        self.assertTrue(hatalar, "hata bekleniyordu")
        self.assertTrue(any(parca in h for h in hatalar), f"'{parca}' içeren hata yok: {hatalar}")

    # geçerli veri ----------------------------------------------------------
    def test_gecerli_kaynak_gecer_ve_dosyalar_yazilir(self):
        veri, hatalar, _ = self.derle()
        self.assertEqual(hatalar, [])
        self.assertEqual(len(veri["iller"]), 81)
        self.assertEqual(len(veri["bolgeler"]), 7)
        self.assertEqual(len(veri["denizler"]), 4)
        self.assertEqual(len(veri["kategoriler"]), 5)
        surum = derle.yaz(veri, self.gecici / "yayin")
        baytlar = (self.gecici / "yayin" / "v1" / "mevsim_veri.json").read_bytes()
        self.assertEqual(surum["sha256"], hashlib.sha256(baytlar).hexdigest())
        self.assertEqual(surum["boyut"], len(baytlar))
        self.assertEqual(surum["veri_surumu"], 5)
        yeniden = json.loads(baytlar)
        self.assertEqual(yeniden["sema_surumu"], 1)
        ispanak = next(u for u in yeniden["urunler"] if u["id"] == "ornek_ispanak")
        self.assertIsNone(ispanak["enerji_kcal_100g"])  # varsayılan alanlar dolduruldu
        self.assertEqual(ispanak["mevsimler"][0]["not"], None)

    def test_main_kontrol_modu_sifir_doner(self):
        kod = derle.main(["--kaynak", str(self.kaynak), "--kontrol", "--veri-surumu", "3"])
        self.assertEqual(kod, 0)

    def test_main_hatada_bir_doner(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.update(kategori_id="yok"))
        kod = derle.main(["--kaynak", str(self.kaynak), "--kontrol", "--veri-surumu", "3"])
        self.assertEqual(kod, 1)

    def test_yil_dondumlu_ve_29_subat_kabul(self):
        self.urun_degistir("ornek_ispanak", lambda u: u["mevsimler"].append(
            mevsim("ornek_ispanak__ege__pazar_yogun__1", donem="pazar_yogun", bas="11-15", bit="02-29")))
        _, hatalar, _ = self.derle()
        self.assertEqual(hatalar, [])

    # madde 3: JSON ---------------------------------------------------------
    def test_bozuk_json_reddedilir(self):
        (self.kaynak / "urunler" / "bozuk.json").write_text("{ \"id\": ", encoding="utf-8")
        self.reddedilmeli("JSON okunamadı")

    def test_dosya_adi_kimlikle_ayni_olmali(self):
        u = self.urun_oku("ornek_ispanak")
        (self.kaynak / "urunler" / "baska_ad.json").write_text(json.dumps(dict(u, id="baska")), encoding="utf-8")
        self.reddedilmeli("dosya adı ürün kimliğiyle aynı olmalı")

    # madde 5: tip / zorunlu / enum ---------------------------------------
    def test_zorunlu_alan_eksik(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.pop("ad"))
        self.reddedilmeli("zorunlu alan eksik: ad")

    def test_tanimsiz_alan(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.update(fiyat=10))
        self.reddedilmeli("tanımsız alan: fiyat")

    def test_yanlis_tip(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.update(aktif="evet"))
        self.reddedilmeli("aktif: tip boolean")

    def test_enum_kapsam_turu(self):
        self.urun_degistir("ornek_ispanak", lambda u: u["mevsimler"][0].update(kapsam_turu="ulke"))
        self.reddedilmeli("'ulke' geçersiz")

    def test_enum_donem_turu(self):
        self.urun_degistir("ornek_ispanak", lambda u: u["mevsimler"][0].update(donem_turu="kis"))
        self.reddedilmeli("'kis' geçersiz")

    def test_enum_guven(self):
        self.urun_degistir("ornek_ispanak", lambda u: u["mevsimler"][0].update(guven="kesin"))
        self.reddedilmeli("'kesin' geçersiz")

    def test_enum_uretim_sekli(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.update(uretim_sekli="sera"))
        self.reddedilmeli("'sera' geçersiz")

    def test_enum_sinyal_turu(self):
        self.not_yaz({"sinyal_turu": "dedikodu"})
        self.reddedilmeli("'dedikodu' geçersiz")

    def test_enerji_tamsayi_olmali(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.update(enerji_kcal_100g=23.5, enerji_kaynak_adi="Test"))
        self.reddedilmeli("enerji_kcal_100g: tip integer")

    # madde 6: kimlik biçimi ve tekrar ------------------------------------
    def test_kimlik_bicimi(self):
        self.urun_degistir("ornek_ispanak", lambda u: u["mevsimler"][0].update(id="Ispanak-Ege"))
        self.reddedilmeli("biçimi geçersiz")

    def test_il_plaka_bicimi(self):
        self.ortak_degistir("iller.json", lambda v: v[0].update(id="1"))
        self.reddedilmeli("'1' biçimi geçersiz")

    def test_tekrar_eden_urun_kimligi(self):
        self.ortak_degistir("kategoriler.json", lambda v: v.append(dict(v[0])))
        self.reddedilmeli("kategoriler: tekrar eden kimlik: balik_deniz")

    def test_tekrar_eden_mevsim_kimligi(self):
        self.urun_degistir("ornek_ispanak", lambda u: u["mevsimler"][1].update(id=u["mevsimler"][0]["id"]))
        self.reddedilmeli("tekrar eden mevsim kimliği")

    # fiyat yok kuralı ------------------------------------------------------
    def test_notta_fiyat_dili_reddedilir(self):
        self.urun_degistir("ornek_ispanak", lambda u: u["mevsimler"][0].update(**{"not": "En ucuz olduğu aylar mart – nisan."}))
        self.reddedilmeli("fiyat yok kuralı")

    def test_kisa_tanimda_fiyat_dili_reddedilir(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.update(kisa_tanim="Uygun fiyatlı kış sebzesi."))
        self.reddedilmeli("kisa_tanim fiyattan söz ediyor")

    def test_arz_dili_kabul(self):
        self.urun_degistir("ornek_ispanak", lambda u: u["mevsimler"][0].update(**{"not": "En bol olduğu aylar mart – nisan."}))
        _, hatalar, _ = self.derle()
        self.assertEqual(hatalar, [])

    # madde 7: başvuru bütünlüğü ------------------------------------------
    def test_bilinmeyen_kategori(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.update(kategori_id="kuruyemis"))
        self.reddedilmeli("bilinmeyen kategori")

    def test_bilinmeyen_kapsam(self):
        self.urun_degistir("ornek_ispanak", lambda u: u["mevsimler"][0].update(kapsam_id="trakya"))
        self.reddedilmeli("bilinmeyen bolge kapsamı: trakya")

    def test_bilinmeyen_gorsel(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.update(gorsel_id="ispanak"))
        self.reddedilmeli("olmayan görsel")

    def test_bilinmeyen_tarif(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.update(tarifler=["ispanak_borek"]))
        self.reddedilmeli("bilinmeyen tarif")

    def test_bilinmeyen_ilgili_urun(self):
        self.urun_degistir("ornek_levrek_ciftlik", lambda u: u.update(ilgili_urun_id="levrek"))
        self.reddedilmeli("bilinmeyen ilgili ürün")

    def test_bilinmeyen_yoresel_il(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.update(yoresel_il_id="82"))
        self.reddedilmeli("yoresel_il_id")

    def test_il_bilinmeyen_bolge(self):
        self.ortak_degistir("iller.json", lambda v: v[0].update(bolge_id="trakya"))
        self.reddedilmeli("iller/01: bilinmeyen bölge")

    def test_bolge_deniz_bilinmeyen(self):
        self.ortak_degistir("bolge_deniz.json", lambda v: v.append({"bolge_id": "ege", "deniz_id": "hazar", "oncelik": 2}))
        self.reddedilmeli("bolge_deniz: bilinmeyen")

    # madde 8: iş kuralları -------------------------------------------------
    def test_gecersiz_gun_ay(self):
        self.urun_degistir("ornek_ispanak", lambda u: u["mevsimler"][0].update(bit="02-30"))
        self.reddedilmeli("geçersiz gün-ay")

    def test_gecersiz_arastirma_tarihi(self):
        self.urun_degistir("ornek_ispanak", lambda u: u["mevsimler"][0].update(arastirma_tarihi="2026-02-30"))
        self.reddedilmeli("geçersiz arastirma_tarihi")

    def test_ciftlik_urununde_mevsim_olamaz(self):
        self.urun_degistir("ornek_levrek_ciftlik", lambda u: u["mevsimler"].append(
            mevsim("ornek_levrek_ciftlik__ege__av__1", tur="deniz", donem="av")))
        self.reddedilmeli("mevsim kaydı olamaz")

    def test_ciftlik_urunu_yil_boyu_olmali(self):
        self.urun_degistir("ornek_levrek_ciftlik", lambda u: u.update(yil_boyu=False))
        self.reddedilmeli("yil_boyu: true olmalı")

    def test_deniz_kapsami_yalniz_balikta(self):
        self.urun_degistir("ornek_ispanak", lambda u: u["mevsimler"].append(
            mevsim("ornek_ispanak__ege__deniz__1", tur="deniz", kid="ege")))
        self.reddedilmeli("deniz kapsamı yalnızca balık")

    def test_il_kaydi_bolge_karsiligi_ister(self):
        self.urun_degistir("ornek_ispanak", lambda u: u["mevsimler"].append(
            mevsim("ornek_ispanak__35__pazar_yogun__1", tur="il", kid="35", donem="pazar_yogun")))
        self.reddedilmeli("bölge düzeyi kaydı yok")

    def test_il_kaydi_bolge_karsiligi_varsa_gecer(self):
        self.urun_degistir("ornek_ispanak", lambda u: u["mevsimler"].append(
            mevsim("ornek_ispanak__35__hasat__1", tur="il", kid="35", donem="hasat")))
        _, hatalar, _ = self.derle()
        self.assertEqual(hatalar, [])

    def test_yoresel_urun_bolge_karsiligi_istemez(self):
        self.urun_yaz({"id": "ornek_yoresel", "ad": "Yöresel (ÖRNEK)", "kategori_id": "sebze", "uretim_sekli": "dogal",
                       "yoresel_il_id": "35", "mevsimler": [mevsim("ornek_yoresel__35__hasat__1", tur="il", kid="35")]})
        _, hatalar, _ = self.derle()
        self.assertEqual(hatalar, [])

    def test_alt_bolge_kaydi_bolge_karsiligi_ister(self):
        self.ortak_degistir("alt_bolgeler.json", lambda v: v.append({"id": "ege_kiyi", "bolge_id": "ege", "ad": "Ege kıyısı"}))
        self.urun_degistir("ornek_ispanak", lambda u: u["mevsimler"].append(
            mevsim("ornek_ispanak__ege_kiyi__depo__1", tur="alt_bolge", kid="ege_kiyi", donem="depo")))
        self.reddedilmeli("bölge düzeyi kaydı yok")

    def test_enerji_aralik_disi(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.update(enerji_kcal_100g=950, enerji_kaynak_adi="Test"))
        self.reddedilmeli("en fazla 900")

    def test_enerji_kaynaksiz(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.update(enerji_kcal_100g=23))
        self.reddedilmeli("enerji_kaynak_adi zorunlu")

    def test_enerji_kaynakli_gecer(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.update(
            enerji_kcal_100g=23, enerji_durum="çiğ", enerji_kaynak_adi="Test kaynağı"))
        _, hatalar, _ = self.derle()
        self.assertEqual(hatalar, [])

    def test_ot_hazirlama_adimi_zorunlu(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.update(kategori_id="ot", tanitim="Bir ot."))
        self.reddedilmeli("en az bir hazırlama adımı zorunlu")

    def test_az_bilinen_tanitim_zorunlu(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.update(az_bilinen=True, hazirlama_adimlari=["Yıkayın."]))
        self.reddedilmeli("tanıtım metni zorunlu")

    def test_az_bilinen_tam_ise_gecer(self):
        self.urun_degistir("ornek_ispanak", lambda u: u.update(
            az_bilinen=True, tanitim="Yapraklı sebze.", hazirlama_adimlari=["Bol suda yıkayın."]))
        _, hatalar, _ = self.derle()
        self.assertEqual(hatalar, [])

    # yıl notları ---------------------------------------------------------
    def not_yaz(self, degisiklik):
        n = {"id": "2026_ornek_1", "urun_id": "ornek_hamsi", "kapsam_turu": "deniz", "kapsam_id": "karadeniz",
             "sinyal_turu": "hal", "baslik": "Örnek", "metin": "Örnek not.", "gecerlilik_bas": "2026-11-15",
             "gecerlilik_bit": "2027-01-31", "kaynak_adi": "Test", "onay_tarihi": "2026-11-16"}
        n.update(degisiklik)
        klasor = self.kaynak / "notlar" / "2026"
        klasor.mkdir(parents=True, exist_ok=True)
        (klasor / f"{n['id']}.json").write_text(json.dumps(n, ensure_ascii=False), encoding="utf-8")

    def test_gecerli_yil_notu(self):
        self.not_yaz({})
        _, hatalar, _ = self.derle()
        self.assertEqual(hatalar, [])

    def test_yil_notu_tarih_sirasi(self):
        self.not_yaz({"gecerlilik_bas": "2027-02-01"})
        self.reddedilmeli("bitişten sonra olamaz")

    def test_yil_notu_bilinmeyen_urun(self):
        self.not_yaz({"urun_id": "kayisi"})
        self.reddedilmeli("bilinmeyen ürün: kayisi")

    def test_yil_notu_yarim_kapsam(self):
        self.not_yaz({"kapsam_id": None})
        self.reddedilmeli("birlikte dolu ya da birlikte boş")

    # madde 9-10: önceki yayına göre ------------------------------------
    def onceki_veri(self):
        veri, hatalar, _ = self.derle(veri_surumu=4)
        self.assertEqual(hatalar, [])
        return copy.deepcopy(veri)

    def test_urun_kaldirilamaz(self):
        self.urun_yaz(dict(self.urun_oku("ornek_ispanak"), id="ispanak", mevsimler=[mevsim("ispanak__ege__hasat__1")]))
        onceki = self.onceki_veri()
        (self.kaynak / "urunler" / "ispanak.json").unlink()
        _, hatalar, _ = self.derle(onceki=onceki)
        self.assertTrue(any("kaldırılamaz" in h for h in hatalar), hatalar)

    def test_ornek_kayit_kaldirilabilir(self):
        onceki = self.onceki_veri()
        self.urun_yaz(dict(self.urun_oku("ornek_ispanak"), id="ispanak", ad="Ispanak",
                           mevsimler=[mevsim("ispanak__ege__hasat__1")]))
        for uid in ("ornek_ispanak", "ornek_hamsi", "ornek_levrek_ciftlik"):
            (self.kaynak / "urunler" / f"{uid}.json").unlink()
        (self.kaynak / "tarifler" / "ornek_hamsi_bugulama.json").unlink()
        _, hatalar, _ = self.derle(onceki=onceki)
        self.assertEqual(hatalar, [])

    def test_gercek_kaynak_gecerli(self):
        _, hatalar, _ = derle.derle(KOK / "kaynak", SEMA, 5)
        self.assertEqual(hatalar, [])

    def test_pasif_yapmak_serbest(self):
        onceki = self.onceki_veri()
        self.urun_degistir("ornek_ispanak", lambda u: u.update(aktif=False))
        _, hatalar, _ = self.derle(onceki=onceki)
        self.assertEqual(hatalar, [])

    def test_veri_surumu_artmali(self):
        onceki = self.onceki_veri()
        _, hatalar, _ = self.derle(onceki=onceki, veri_surumu=4)
        self.assertTrue(any("büyük olmalı" in h for h in hatalar), hatalar)

    def test_urun_sayisi_yuzde_doksan(self):
        onceki = self.onceki_veri()
        onceki["urunler"] = onceki["urunler"] + [dict(onceki["urunler"][0], id=f"eski_{i}") for i in range(30)]
        for i in range(30):
            self.urun_yaz(dict(self.urun_oku("ornek_ispanak"), id=f"eski_{i}", mevsimler=[]))
        (self.kaynak / "urunler" / "eski_0.json").unlink()
        for i in range(1, 5):
            (self.kaynak / "urunler" / f"eski_{i}.json").unlink()
        _, hatalar, _ = self.derle(onceki=onceki)
        self.assertTrue(any("%90" in h for h in hatalar), hatalar)

    # tanınırlık sırası -------------------------------------------------------
    def test_bilinirlik_istege_bagli_ve_gecerli_deger_gecer(self):
        self.urun_degistir("ornek_hamsi", lambda u: u.update(bilinirlik=1, siralama=1))
        self.urun_degistir("ornek_levrek_ciftlik", lambda u: u.update(bilinirlik=2, siralama=2))
        veri, hatalar, _ = self.derle()
        self.assertEqual(hatalar, [])
        self.assertNotIn("bilinirlik", next(u for u in veri["urunler"] if u["id"] == "ornek_ispanak"))

    def test_bilinirlik_aralik_disi(self):
        self.urun_degistir("ornek_hamsi", lambda u: u.update(bilinirlik=6, siralama=1))
        self.reddedilmeli("en fazla 5")
        self.urun_degistir("ornek_hamsi", lambda u: u.update(bilinirlik=0, siralama=1))
        self.reddedilmeli("en az 1")

    def test_siralama_tamsayi_ve_pozitif(self):
        self.urun_degistir("ornek_hamsi", lambda u: u.update(bilinirlik=1, siralama=0))
        self.reddedilmeli("en az 1")
        self.urun_degistir("ornek_hamsi", lambda u: u.update(bilinirlik=1, siralama="1"))
        self.reddedilmeli("tip integer/null")

    def test_ayni_kategoride_tekrar_eden_siralama(self):
        self.urun_degistir("ornek_hamsi", lambda u: u.update(bilinirlik=1, siralama=3))
        self.urun_degistir("ornek_levrek_ciftlik", lambda u: u.update(bilinirlik=1, siralama=3))
        self.reddedilmeli("kategorisinde")

    def test_farkli_kategoride_ayni_siralama_serbest(self):
        self.urun_degistir("ornek_hamsi", lambda u: u.update(bilinirlik=1, siralama=1))
        self.urun_degistir("ornek_ispanak", lambda u: u.update(bilinirlik=1, siralama=1))
        _, hatalar, _ = self.derle()
        self.assertEqual(hatalar, [])

    def test_az_bilinen_ust_sirada_olamaz(self):
        def degis(u):
            u.update(az_bilinen=True, bilinirlik=2, siralama=1, tanitim="Tanıtım.",
                     hazirlama_adimlari=["Yıkayın."])
        self.urun_degistir("ornek_hamsi", degis)
        self.reddedilmeli("en az 3")

    def test_gercek_kaynakta_her_urunun_sirasi_var(self):
        veri, _, _ = derle.derle(KOK / "kaynak", SEMA, 5)
        for u in veri["urunler"]:
            self.assertIsInstance(u.get("bilinirlik"), int, u["id"])
            self.assertIsInstance(u.get("siralama"), int, u["id"])
        hamsi = next(u for u in veri["urunler"] if u["id"] == "hamsi")
        self.assertEqual((hamsi["bilinirlik"], hamsi["siralama"]), (1, 1))

    def test_siralama_dosyasi_kurallari(self):
        import ege_icerik_aktar as aktar
        yol = self.gecici / "bilinirlik.json"
        urunler = {"a": {}, "b": {"yoresel_il_id": "35"}, "c": {}, "d": {"az_bilinen": True}}
        kategori = {"a": "sebze", "b": "sebze", "c": "sebze", "d": "sebze"}

        def dene(liste):
            yol.write_text(json.dumps({"aciklama": "", "sebze": liste}), encoding="utf-8")
            hatalar = []
            return aktar.bilinirlik_oku(yol, urunler, kategori, hatalar), hatalar

        sonuc, hatalar = dene([["a", 1], ["b", 1], ["c", 2], ["d", 3]])
        self.assertEqual(hatalar, [])
        self.assertEqual(sonuc["c"], (2, 3))
        _, hatalar = dene([["a", 2], ["b", 2], ["c", 1], ["d", 3]])
        self.assertTrue(any("daha az bilinen" in h for h in hatalar), hatalar)
        _, hatalar = dene([["b", 1], ["a", 1], ["c", 2], ["d", 3]])
        self.assertTrue(any("yöresel" in h for h in hatalar), hatalar)
        _, hatalar = dene([["a", 1], ["b", 1], ["c", 2], ["d", 2]])
        self.assertTrue(any("en az 3" in h for h in hatalar), hatalar)
        _, hatalar = dene([["a", 1], ["b", 1], ["c", 2]])
        self.assertTrue(any("sıralama dosyasında yok" in h for h in hatalar), hatalar)

    def test_sema_surumu_sabit(self):
        veri, _, _ = self.derle()
        veri["sema_surumu"] = 2
        hatalar = []
        derle.sema_dogrula(veri, json.loads(SEMA.read_text(encoding="utf-8")), json.loads(SEMA.read_text(encoding="utf-8")), "kok", hatalar)
        self.assertTrue(any("sema_surumu" in h for h in hatalar))


if __name__ == "__main__":
    unittest.main()
