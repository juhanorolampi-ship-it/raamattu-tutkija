import unittest
from app import lataa_raamattu, etsi_viittaukset_tekstista

class TestViittaustenTunnistus(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        print("Ladataan Raamattu-data testejä varten...")
        _, cls.book_map, _, cls.book_data_map, _, cls.sorted_aliases = lataa_raamattu()
        print("Data ladattu.")

    def test_tunnistaa_perusviittauksen(self):
        """Testaa, että yksinkertainen viittaus tunnistetaan."""
        teksti = "Tärkeä jae on Joh. 3:16 ja myös Room. 5:8."
        viittaukset = etsi_viittaukset_tekstista(teksti, self.book_map, self.book_data_map, self.sorted_aliases)
        self.assertEqual(len(viittaukset), 2)
        self.assertIn(viittaukset[0]['book_name'], ['Johannes', 'Johanneksen evankeliumi'])
        self.assertEqual(viittaukset[1]['book_name'], 'Roomalaiskirje')

    def test_tunnistaa_pisteellisen_lyhenteen(self):
        """Testaa, että lyhenne, jonka perässä on piste, tunnistetaan (esim. Luuk.)."""
        teksti = "Tämä mainitaan kohdassa Luuk. 16:10."
        viittaukset = etsi_viittaukset_tekstista(teksti, self.book_map, self.book_data_map, self.sorted_aliases)
        self.assertEqual(len(viittaukset), 1)
        self.assertIn(viittaukset[0]['book_name'], ['Luukas', 'Luukkaan evankeliumi'])

    def test_tunnistaa_sulkeiden_sisalla(self):
        """Testaa, että sulkeiden sisällä oleva viittaus tunnistetaan (esim. Hepr.)."""
        # KORJATTU "Hepr." -> "Hebr." vastaamaan bible.json-dataa
        teksti = "Tämä vaatii ojennusta (Hebr. 10:24-25)."
        viittaukset = etsi_viittaukset_tekstista(teksti, self.book_map, self.book_data_map, self.sorted_aliases)
        self.assertEqual(len(viittaukset), 1)
        self.assertEqual(viittaukset[0]['book_name'], 'Heprealaiskirje')
        self.assertEqual(viittaukset[0]['start_verse'], 24)
        self.assertEqual(viittaukset[0]['end_verse'], 25)

    def test_tunnistaa_numeroidun_kirjan(self):
        """Testaa, että numeroitu kirja tunnistetaan oikein (esim. 2. Joh)."""
        teksti = "Rakkaudesta puhuu myös 2. Joh 1:6."
        viittaukset = etsi_viittaukset_tekstista(teksti, self.book_map, self.book_data_map, self.sorted_aliases)
        self.assertEqual(len(viittaukset), 1)
        self.assertEqual(viittaukset[0]['book_name'], '2. Johanneksen kirje')

    def test_ei_tunnista_normaalia_tekstia(self):
        """Testaa, että funktio ei virheellisesti tunnista tavallista tekstiä viittaukseksi."""
        teksti = "Tässä lauseessa ei ole Raamatun viittausta."
        viittaukset = etsi_viittaukset_tekstista(teksti, self.book_map, self.book_data_map, self.sorted_aliases)
        self.assertEqual(len(viittaukset), 0)

if __name__ == '__main__':
    unittest.main()