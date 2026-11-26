"""Filtre et tri par formation sur la liste des utilisateurs."""
from datetime import timedelta

from django.urls import reverse

from core.models import Course, CourseSession, Enrollment, RoleKey

from .base import BusinessTestBase


class UserListFormationTests(BusinessTestBase):
    def setUp(self):
        super().setUp()
        self.client = self.client_for(self.super_admin)
        self.url = reverse('core:dashboard:user-list')

        self.automatisation = Course.objects.create(
            title='Automatisation',
            domain='Informatique',
            description='Formation de test',
            duration_months=2,
            fee_amount=50000,
            active=True,
        )
        self.groupe_auto = CourseSession.objects.create(
            course=self.automatisation,
            starts_at=self.today - timedelta(days=10),
            ends_at=self.today + timedelta(days=30),
            schedule='Mer 14h-16h',
            capacity=10,
            status=CourseSession.Status.ACTIVE,
        )
        self.etudiant_auto = self.make_user(
            RoleKey.ETUDIANT, 'etudiant.auto@test.local')
        self.etudiant_auto.last_name = 'Zulu'
        self.etudiant_auto.save(update_fields=['last_name'])
        Enrollment.objects.create(
            student=self.etudiant_auto,
            session=self.groupe_auto,
            status=Enrollment.Status.ACTIVE,
            start_date=self.today,
            tariff_amount=50000,
            net_amount=50000,
            registered_by=self.secretaire,
        )

    def test_formation_n_apparait_que_pour_les_etudiants(self):
        etudiants = self.client.get(self.url, {'role': RoleKey.ETUDIANT.value})
        self.assertEqual(etudiants.status_code, 200)
        self.assertTrue(etudiants.context['show_formation'])
        self.assertContains(etudiants, 'name="course"')
        self.assertContains(etudiants, self.automatisation.title)

        autres = self.client.get(
            self.url, {'role': RoleKey.ASSISTANT_ADMIN.value})
        self.assertFalse(autres.context['show_formation'])
        self.assertNotContains(autres, 'name="course"')

    def test_filtre_formation_ne_garde_que_les_inscrits(self):
        response = self.client.get(self.url, {
            'role': RoleKey.ETUDIANT.value,
            'course': str(self.course.id),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['course_filter'], str(self.course.id))
        users = list(response.context['page'].object_list)
        self.assertIn(self.etudiant, users)
        self.assertNotIn(self.etudiant_auto, users)

    def test_tri_par_formation_regroupe_les_etudiants(self):
        response = self.client.get(self.url, {
            'role': RoleKey.ETUDIANT.value,
            'sort': 'formation',
        })
        self.assertEqual(response.status_code, 200)
        users = list(response.context['page'].object_list)
        self.assertEqual(users[0], self.etudiant_auto)
        self.assertEqual(users[0].formation, self.automatisation.title)
        self.assertEqual(users[1], self.etudiant)
        self.assertEqual(users[1].formation, self.course.title)

    def test_valeurs_invalides_retombent_sur_le_tri_par_defaut(self):
        response = self.client.get(self.url, {
            'role': RoleKey.ETUDIANT.value,
            'course': 'pas-un-uuid',
            'sort': 'inconnu',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['course_filter'], '')
        self.assertEqual(response.context['sort_filter'], 'recent')

        sans_role = self.client.get(self.url, {
            'role': '',
            'sort': 'formation',
        })
        self.assertEqual(sans_role.context['sort_filter'], 'recent')
