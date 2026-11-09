from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from core.eleves_import import MARQUE as MARQUE_CLASSEURS
from core.models import (
    Course, CourseSession, Enrollment, Payment, Role, RoleKey, User, UserRole,
)


class PurgerDonneesFictivesTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email='admin@example.test', password='test-password'
        )
        self.etudiant = User.objects.create_user(
            email='etudiant@example.test', password='test-password'
        )
        role_etudiant, _ = Role.objects.get_or_create(
            key=RoleKey.ETUDIANT,
            defaults={'label': RoleKey.ETUDIANT.label},
        )
        UserRole.objects.create(user=self.etudiant, role=role_etudiant)

        self.formation_importee = Course.objects.create(
            title='Formation importee', domain='Test', fee_amount=100,
            description=f'Tarif {MARQUE_CLASSEURS}',
        )
        self.groupe_importe = CourseSession.objects.create(
            course=self.formation_importee, starts_at='2026-01-01',
            ends_at='2026-12-31', schedule=MARQUE_CLASSEURS,
        )
        self.inscription_importee = Enrollment.objects.create(
            student=self.etudiant, session=self.groupe_importe,
            notes=f'{MARQUE_CLASSEURS} — classeur.xlsx',
        )
        self.paiement_importe = Payment.objects.create(
            enrollment=self.inscription_importee, amount=100,
            method=Payment.Method.CASH, note=MARQUE_CLASSEURS,
        )

        self.utilisateur_fictif = User.objects.create_user(
            email='fictif@example.test', password='test-password'
        )
        self.formation_fictive = Course.objects.create(
            title='Formation fictive', domain='Test', fee_amount=100,
        )
        self.groupe_fictif = CourseSession.objects.create(
            course=self.formation_fictive, starts_at='2026-01-01',
            ends_at='2026-12-31',
        )
        self.inscription_fictive = Enrollment.objects.create(
            student=self.utilisateur_fictif, session=self.groupe_fictif,
        )
        self.paiement_fictif = Payment.objects.create(
            enrollment=self.inscription_fictive, amount=100,
            method=Payment.Method.CASH,
        )

    def test_previsualisation_ne_supprime_rien(self):
        sortie = StringIO()

        call_command('purger_donnees_fictives', stdout=sortie)

        self.assertIn('Previsualisation', sortie.getvalue())
        self.assertEqual(User.objects.count(), 3)
        self.assertEqual(Enrollment.objects.count(), 2)
        self.assertEqual(Payment.objects.count(), 2)

    @patch('core.management.commands.purger_donnees_fictives.sauvegarder_base')
    def test_purge_conserve_les_donnees_importees_et_le_superadmin(self, sauvegarder):
        sauvegarder.return_value = Path('copie.sqlite3')

        call_command('purger_donnees_fictives', ecrire=True, stdout=StringIO())

        self.assertEqual(User.objects.count(), 2)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.etudiant.pk).exists())
        self.assertFalse(User.objects.filter(pk=self.utilisateur_fictif.pk).exists())
        self.assertTrue(Enrollment.objects.filter(pk=self.inscription_importee.pk).exists())
        self.assertTrue(Payment.objects.filter(pk=self.paiement_importe.pk).exists())
        self.assertFalse(Enrollment.objects.filter(pk=self.inscription_fictive.pk).exists())
        self.assertFalse(Payment.objects.filter(pk=self.paiement_fictif.pk).exists())
        self.assertTrue(Course.objects.filter(pk=self.formation_importee.pk).exists())
        self.assertFalse(Course.objects.filter(pk=self.formation_fictive.pk).exists())
        self.assertTrue(CourseSession.objects.filter(pk=self.groupe_importe.pk).exists())
        self.assertFalse(CourseSession.objects.filter(pk=self.groupe_fictif.pk).exists())
        sauvegarder.assert_called_once_with()
