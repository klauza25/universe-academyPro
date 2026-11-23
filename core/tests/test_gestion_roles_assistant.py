"""L'assistant administratif gère les comptes et les rôles de A à Z.

L'ADMIN reste en lecture seule et les postes privilégiés (super
administrateur, administrateur, direction) ne peuvent pas être attribués par
l'assistant : la gestion complète ne doit pas devenir une élévation de
privilèges.
"""
from django.urls import reverse

from core.models import AccountStatus, RoleKey, User

from .base import BusinessTestBase

LIST_URL = 'core:dashboard:user-list'
CREATE_URL = 'core:dashboard:user-create'
DETAIL_URL = 'core:dashboard:user-detail'
EDIT_URL = 'core:dashboard:user-edit'
ROLES_URL = 'core:dashboard:user-role-assign'
STATUS_URL = 'core:dashboard:user-status-change'


class AssistantUserManagementTests(BusinessTestBase):
    def setUp(self):
        super().setUp()
        self.client_assistant = self.client_for(self.assistant)

    def test_assistant_reaches_user_screens_and_navigation(self):
        response = self.client_assistant.get(reverse(LIST_URL))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['can_manage_users'])
        self.assertContains(response, reverse(CREATE_URL))
        self.assertContains(
            response, reverse(EDIT_URL, args=[self.secretaire.id]))

        tableau = self.client_assistant.get(
            reverse('core:dashboard:comptabilite-dashboard'))
        self.assertContains(tableau, reverse(LIST_URL))

        for route, args in (
            (CREATE_URL, ()),
            (DETAIL_URL, (self.secretaire.id,)),
            (EDIT_URL, (self.secretaire.id,)),
        ):
            with self.subTest(route=route):
                self.assertEqual(
                    self.client_assistant.get(reverse(route, args=args)).status_code,
                    200,
                )

    def test_assistant_creates_account_with_role(self):
        response = self.client_assistant.post(reverse(CREATE_URL), {
            'first_name': 'Nouveau',
            'last_name': 'Responsable',
            'email': 'nvlle.responsable@test.local',
            'phone': '+242060000099',
            'role': RoleKey.RESPONSABLE_PEDAGOGIQUE,
            'session': '',
            'password': 'AssistantPass123!',
        })
        self.assertRedirects(
            response, reverse(LIST_URL), fetch_redirect_response=False)
        created = User.objects.get(email='nvlle.responsable@test.local')
        self.assertTrue(created.has_role(RoleKey.RESPONSABLE_PEDAGOGIQUE))
        self.assertTrue(created.internal_code.startswith('UA-RPD'))
        self.assert_audited('USER_CREATE', created.id)

    def test_assistant_create_form_hides_privileged_roles(self):
        response = self.client_assistant.get(reverse(CREATE_URL))
        choix = {
            cle for cle, ___ in response.context['form'].fields['role'].choices
            if cle
        }
        self.assertNotIn(
            {'SUPER_ADMIN', 'ADMIN', 'DIRECTION'}, choix)
        self.assertNotIn(
            {'SECRETAIRE', 'COMPTABLE', 'ACCUEIL'}, choix)
        self.assertIn(RoleKey.ASSISTANT_ADMIN, choix)

    def test_assistant_cannot_create_a_privileged_account(self):
        before = User.objects.count()
        response = self.client_assistant.post(reverse(CREATE_URL), {
            'first_name': 'Fausse',
            'last_name': 'Direction',
            'email': 'fausse.direction@test.local',
            'phone': '',
            'role': RoleKey.DIRECTION,
            'session': '',
            'password': 'AssistantPass123!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), before)
        self.assertFalse(
            User.objects.filter(email='fausse.direction@test.local').exists())

    def test_assistant_edits_account_and_status(self):
        response = self.client_assistant.post(
            reverse(EDIT_URL, args=[self.secretaire.id]), {
                'first_name': 'Modifié',
                'last_name': 'Par assistant',
                'email': self.secretaire.email,
                'phone': '+242060000088',
                'account_status': AccountStatus.ACTIVE,
            })
        self.assertEqual(response.status_code, 302)
        self.secretaire.refresh_from_db()
        self.assertEqual(self.secretaire.first_name, 'Modifié')
        self.assert_audited('USER_EDIT', self.secretaire.id)

        response = self.client_assistant.post(
            reverse(STATUS_URL, args=[self.secretaire.id]),
            {'account_status': AccountStatus.SUSPENDED})
        self.assertEqual(response.status_code, 302)
        self.secretaire.refresh_from_db()
        self.assertEqual(self.secretaire.account_status, AccountStatus.SUSPENDED)
        self.assert_audited('USER_STATUS_CHANGE', self.secretaire.id)

    def test_assistant_assigns_and_removes_a_business_role(self):
        response = self.client_assistant.post(
            reverse(ROLES_URL, args=[self.etudiant.id]),
            {'role_key': RoleKey.RESPONSABLE_PEDAGOGIQUE, 'action': 'add'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.etudiant.has_role(RoleKey.RESPONSABLE_PEDAGOGIQUE))
        self.assert_audited('ROLE_ASSIGN', self.etudiant.id)

        response = self.client_assistant.post(
            reverse(ROLES_URL, args=[self.etudiant.id]),
            {'role_key': RoleKey.RESPONSABLE_PEDAGOGIQUE, 'action': 'remove'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.etudiant.has_role(RoleKey.RESPONSABLE_PEDAGOGIQUE))
        self.assert_audited('ROLE_REMOVE', self.etudiant.id)

    def test_assistant_cannot_grant_a_dissolved_role(self):
        for role_key in ('SECRETAIRE', 'COMPTABLE', 'ACCUEIL'):
            with self.subTest(role=role_key):
                response = self.client_assistant.post(
                    reverse(ROLES_URL, args=[self.etudiant.id]),
                    {'role_key': role_key, 'action': 'add'})
                self.assertEqual(response.status_code, 302)
                self.assertFalse(self.etudiant.has_role(role_key))

    def test_assistant_cannot_grant_a_privileged_role(self):
        for role_key in (
            RoleKey.SUPER_ADMIN, RoleKey.ADMIN, RoleKey.DIRECTION,
        ):
            with self.subTest(role=role_key):
                response = self.client_assistant.post(
                    reverse(ROLES_URL, args=[self.etudiant.id]),
                    {'role_key': role_key, 'action': 'add'})
                self.assertEqual(response.status_code, 403)
                self.assertFalse(self.etudiant.has_role(role_key))

        fiche = self.client_assistant.get(
            reverse(DETAIL_URL, args=[self.etudiant.id]))
        self.assertNotIn(
            {'SUPER_ADMIN', 'ADMIN', 'DIRECTION'},
            {role.key for role in fiche.context['available_roles']},
        )

    def test_assistant_cannot_change_own_roles(self):
        response = self.client_assistant.post(
            reverse(ROLES_URL, args=[self.assistant.id]),
            {'role_key': RoleKey.RESPONSABLE_PEDAGOGIQUE, 'action': 'add'})
        self.assertEqual(response.status_code, 403)
        self.assistant.refresh_from_db()
        self.assertFalse(self.assistant.has_role(RoleKey.RESPONSABLE_PEDAGOGIQUE))

    def test_other_roles_stay_outside_user_management(self):
        for user in (self.direction, self.peda, self.formateur, self.etudiant):
            with self.subTest(role=user.primary_role):
                client = self.client_for(user)
                self.assertEqual(
                    client.get(reverse(LIST_URL)).status_code, 403)
                self.assertEqual(
                    client.get(reverse(CREATE_URL)).status_code, 403)
