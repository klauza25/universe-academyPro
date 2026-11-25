"""Identifiants privés des étudiants importés : génération et première connexion."""
import csv
import io

from django.contrib.auth import authenticate
from django.urls import reverse

from core import identifiants
from core.models import (
    AccountStatus, AuditLog, Course, CourseSession, Enrollment, Notification,
    Role, RoleKey, User, UserRole,
)

from .base import BusinessTestBase, TEST_PASSWORD


class IdentifiantsTests(BusinessTestBase):
    def setUp(self):
        self.admin_client = self.client_for(self.super_admin)

    @staticmethod
    def etudiant_sans_mot_de_passe(prenom, nom, email):
        # ``create_user(password=None)`` pose un mot de passe inutilisable,
        # exactement comme l'import des classeurs (``_ecrire_compte``).
        user = User.objects.create_user(
            email=email, first_name=prenom, last_name=nom,
            account_status=AccountStatus.PENDING_APPROVAL,
        )
        user.set_unusable_password()
        user.save(update_fields=['password'])
        UserRole.objects.get_or_create(
            user=user, role=Role.objects.get(key=RoleKey.ETUDIANT))
        return user

    def test_code_formation_mapping(self):
        cas = {
            'Excel avancé': 'e',
            'Informatique générale': 'i',
            'Informatique de gestion': 'g',
            'Maintenance informatique': 'm',
            'Bureautique': 'b',
            'Anglais': 'a',
            'Développement Web': 'd',
            'Gestion de projet': 'g',
            '': 'x',
        }
        for titre, code in cas.items():
            with self.subTest(titre=titre):
                self.assertEqual(identifiants.code_formation(titre), code)

    def test_adresse_unique_avec_suffixe(self):
        self.etudiant_sans_mot_de_passe('Jean', 'Dupont', 'a@test.local')
        second = self.etudiant_sans_mot_de_passe('Jean', 'Dupont', 'b@test.local')
        self.assertEqual(
            identifiants.adresse_pour(second, 'e'), 'jean.dupont-e@universe.academy')
        # Une fois la première adresse posée, le doublon reçoit un suffixe.
        second.email = 'jean.dupont-e@universe.academy'
        second.save(update_fields=['email'])
        self.assertEqual(
            identifiants.adresse_pour(second, 'e'), 'jean.dupont-e-2@universe.academy')

    def test_emettre_active_account_and_notifie(self):
        etudiant = self.etudiant_sans_mot_de_passe(
            'Marie', 'Clarisse', 'marie@test.local')
        # Une inscription Excel avancé donne le suffixe « e ».
        course = Course.objects.create(
            title='Excel avancé', domain='Bureautique', fee_amount=50000,
            duration_months=3,
        )
        session = CourseSession.objects.create(
            course=course, starts_at=self.today, ends_at=self.today,
            capacity=10, status=CourseSession.Status.ACTIVE,
        )
        Enrollment.objects.create(
            student=etudiant, session=session, status=Enrollment.Status.ACTIVE,
            start_date=self.today,
        )

        lignes = identifiants.emettre([etudiant])

        etudiant.refresh_from_db()
        self.assertEqual(
            lignes[0]['email'], 'marie.clarisse-e@universe.academy')
        self.assertEqual(etudiant.email, lignes[0]['email'])
        self.assertEqual(etudiant.username, lignes[0]['email'])
        self.assertEqual(etudiant.account_status, AccountStatus.ACTIVE)
        self.assertTrue(etudiant.password_must_change)
        self.assertTrue(etudiant.has_usable_password())
        self.assertTrue(etudiant.check_password(lignes[0]['mot_de_passe']))
        notification = Notification.objects.get(user=etudiant)
        self.assertEqual(
            notification.notification_type, Notification.Type.CREDENTIALS_ISSUED)
        self.assertIn(lignes[0]['mot_de_passe'], notification.message)
        self.assertEqual(
            notification.link, reverse('core:dashboard:password-change-required'))

    def test_page_reservee_aux_gestionnaires(self):
        response = self.client_for(self.etudiant).get(
            reverse('core:dashboard:identifiants-page'))
        self.assertEqual(response.status_code, 403)

    def test_generation_renvoie_csv_prive(self):
        etudiant = self.etudiant_sans_mot_de_passe(
            'Jean', 'Dupont', 'jean@test.local')
        self.assertFalse(etudiant.has_usable_password())
        response = self.admin_client.post(
            reverse('core:dashboard:identifiants-generer'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Disposition'].startswith('attachment'))
        contenu = response.content.decode('utf-8-sig')
        lignes = list(csv.reader(io.StringIO(contenu), delimiter=';'))
        self.assertEqual(
            lignes[0], ['Courriel', 'Mot de passe temporaire', 'Code interne',
                        'Prénom', 'Nom', 'Formation'])
        self.assertEqual(lignes[1][0], 'jean.dupont-x@universe.academy')
        etudiant.refresh_from_db()
        self.assertEqual(etudiant.email, lignes[1][0])
        self.assertTrue(etudiant.password_must_change)
        audit = AuditLog.objects.get(action='CREDENTIALS_ISSUE')
        self.assertNotIn(lignes[1][1], str(audit.after_summary))

    def test_deuxieme_generation_ne_reinitialise_pas(self):
        etudiant = self.etudiant_sans_mot_de_passe(
            'Jean', 'Dupont', 'jean@test.local')
        url = reverse('core:dashboard:identifiants-generer')
        premier = self.admin_client.post(url)
        secret = list(csv.reader(
            io.StringIO(premier.content.decode('utf-8-sig')), delimiter=';'))[1][1]
        second = self.admin_client.post(url)
        self.assertEqual(second.status_code, 302)
        etudiant.refresh_from_db()
        self.assertTrue(etudiant.check_password(secret))
        self.assertEqual(
            Notification.objects.filter(user=etudiant).count(), 1)

    def test_connexion_force_changement_et_deblocage(self):
        etudiant = self.etudiant_sans_mot_de_passe(
            'Jean', 'Dupont', 'jean@test.local')
        identifiants.emettre([etudiant])
        etudiant.refresh_from_db()
        secret = Notification.objects.get(user=etudiant).message.split(
            'Mot de passe temporaire : ')[1].split('\n')[0]
        client = self.client_class()
        self.assertTrue(client.login(email=etudiant.email, password=secret))
        response = client.get(reverse('core:dashboard:user-list'))
        self.assertRedirects(
            response, reverse('core:dashboard:password-change-required'),
            fetch_redirect_response=False)
        self.assertTrue(
            authenticate(username=etudiant.email, password=secret))

        response = client.post(
            reverse('core:dashboard:password-change-required'), {
                'current_password': secret,
                'new_password': 'NouveauPass123!',
                'new_password_confirm': 'NouveauPass123!',
            })
        self.assertRedirects(
            response, reverse('core:dashboard:dashboard-router'),
            fetch_redirect_response=False)
        etudiant.refresh_from_db()
        self.assertFalse(etudiant.password_must_change)
        self.assertTrue(etudiant.check_password('NouveauPass123!'))
        self.assertEqual(
            client.get(reverse('core:dashboard:password-change-required')).status_code,
            302)
