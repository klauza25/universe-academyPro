"""La bande de compteurs commune à tous les tableaux de bord.

Trois nombres seulement : tous les comptes, les étudiants, le staff. Ils
doivent rester justes quand un compte n'a pas encore de rôle ou quand une
personne cumule un rôle étudiant et un rôle d'encadrement. La bande en est
l'unique affiche : aucune carte d'un tableau de bord ne doit reprendre l'un de
ces trois nombres.
"""
import re
from pathlib import Path

from django.conf import settings
from django.urls import reverse

from core.models import AccountStatus, RoleKey, User, UserRole
from core.tests.base import BusinessTestBase, TEST_PASSWORD
from core.utils import platform_counts


class PlatformCountsTest(BusinessTestBase):
    def test_counts_accounts_students_and_staff(self):
        counts = platform_counts()

        self.assertEqual(counts['total_users'], 8)
        self.assertEqual(counts['total_students'], 1)
        self.assertEqual(counts['total_staff'], 7)

    def test_account_without_role_counts_only_as_user(self):
        User.objects.create_user(
            email='sansrole@test.local',
            password=TEST_PASSWORD,
            account_status=AccountStatus.PENDING_APPROVAL,
        )

        counts = platform_counts()

        self.assertEqual(counts['total_users'], 9)
        self.assertEqual(counts['total_students'], 1)
        self.assertEqual(counts['total_staff'], 7)

    def test_dual_role_counts_in_both_groups(self):
        UserRole.objects.create(user=self.etudiant, role=self.roles[RoleKey.FORMATEUR])

        counts = platform_counts()

        self.assertEqual(counts['total_students'], 1)
        self.assertEqual(counts['total_staff'], 8)

    def test_every_role_dashboard_shows_the_three_counters(self):
        for user, url_name in self.tableaux():
            with self.subTest(dashboard=url_name):
                response = self.client_for(user).get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'class="ua-compteur"', count=3)
                self.assertContains(
                    response,
                    '<p class="ua-compteur-value">8</p>',
                    count=1,
                )
                self.assertContains(
                    response,
                    '<p class="ua-compteur-value">1</p>',
                    count=1,
                )
                self.assertContains(
                    response,
                    '<p class="ua-compteur-value">7</p>',
                    count=1,
                )

    def test_les_cartes_ne_reprennent_jamais_un_compteur_de_la_bande(self):
        carte = re.compile(
            r'(?:value=|ua-hero-card-value">\s*\{\{\s*)(total_users|total_students|total_staff)\b'
        )
        dossier = Path(settings.BASE_DIR) / 'templates' / 'dashboard'
        fautes = {}
        for chemin in sorted(dossier.rglob('*.html')):
            if chemin.name == '_compteurs.html':
                continue
            reprises = sorted(set(carte.findall(chemin.read_text(encoding='utf-8'))))
            if reprises:
                fautes[chemin.relative_to(dossier).as_posix()] = reprises

        self.assertEqual(fautes, {})

    def tableaux(self):
        return [
            (self.super_admin, 'core:dashboard:super-admin-dashboard'),
            (self.admin, 'core:dashboard:admin-dashboard'),
            (self.direction, 'core:dashboard:direction-dashboard'),
            (self.assistant, 'core:dashboard:comptabilite-dashboard'),
            (self.secretaire, 'core:dashboard:secretaire-dashboard'),
            (self.peda, 'core:dashboard:resp-peda-dashboard'),
            (self.formateur, 'core:dashboard:formateur-dashboard'),
            (self.etudiant, 'core:dashboard:etudiant-dashboard'),
            # L'accueil est tenu par l'assistant administratif depuis la fusion
            # des postes ; il ouvre le même tableau de bord que la caisse.
            (self.assistant, 'core:dashboard:accueil-dashboard'),
        ]
