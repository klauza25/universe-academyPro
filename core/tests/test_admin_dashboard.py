"""Gabarits et compteurs de l'administration Django personnalisée."""
from django.test import TestCase
from django.urls import reverse

from core.models import User
from core.templatetags import admin_dashboard


class AdminDashboardTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email='admin-dashboard@example.com',
            password='MotDePasseFort123!',
            first_name='Admin',
            last_name='Test',
        )
        self.client.force_login(self.admin)

    def test_l_accueil_admin_porte_l_identite_et_les_compteurs(self):
        response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 200)
        contenu = response.content.decode('utf-8')
        self.assertIn('Univers Academy', contenu)
        self.assertIn('admin-univers.css', contenu)
        self.assertIn('Chiffres clés', contenu)
        self.assertIn('Activité récente', contenu)

    def test_la_page_de_connexion_admin_est_personnalisee(self):
        self.client.logout()

        response = self.client.get(reverse('admin:login'))

        self.assertEqual(response.status_code, 200)
        contenu = response.content.decode('utf-8')
        self.assertIn('Administration Univers Academy', contenu)
        self.assertIn('admin-univers.css', contenu)

    def test_les_compteurs_sont_lus_dans_les_modeles(self):
        stats = admin_dashboard.ua_admin_stats()

        self.assertEqual(
            set(stats), {'utilisateurs', 'etudiants', 'formations', 'paiements'})
        self.assertTrue(all(isinstance(valeur, int) for valeur in stats.values()))
        self.assertGreaterEqual(stats['utilisateurs'], 1)
