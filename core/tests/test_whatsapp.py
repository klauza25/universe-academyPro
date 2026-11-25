"""Liens WhatsApp à partir des numéros affichés dans le back-office."""
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from core.templatetags.ui import whatsapp


class WhatsAppFilterTests(SimpleTestCase):
    def test_numero_vide_ne_donne_pas_de_lien(self):
        self.assertEqual(whatsapp(''), '')
        self.assertEqual(whatsapp(None), '')

    def test_formats_congolais(self):
        cas = {
            '+242 06 111 22 33': 'https://wa.me/242061112233',
            '061112233': 'https://wa.me/242061112233',
            '00242 06 11 12 23': 'https://wa.me/24206111223',
            '242 06 111 22 33': 'https://wa.me/242061112233',
            '067813740': 'https://wa.me/242067813740',
            '67813740': 'https://wa.me/242067813740',
        }
        for numero, attendu in cas.items():
            with self.subTest(numero=numero):
                self.assertEqual(whatsapp(numero), attendu)

    def test_indicatif_etranger_conserve(self):
        self.assertEqual(
            whatsapp('+33 6 12 34 56 78'), 'https://wa.me/33612345678')

    def test_partial_affiche_le_lien_ou_un_tiret(self):
        html = render_to_string('dashboard/_whatsapp.html', {
            'phone': '+242 06 111 22 33',
        })
        self.assertIn('https://wa.me/242061112233', html)
        self.assertIn('+242 06 111 22 33', html)
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertEqual(
            render_to_string('dashboard/_whatsapp.html', {'phone': ''}).strip(),
            '—')
