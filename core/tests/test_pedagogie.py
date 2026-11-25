"""Tests de la pédagogie : programmes, séances, présences et ressources."""
from datetime import time as dt_time, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from core.admin import FormuleGroupeAdmin
from core.forms import (
    EnrollmentForm, NewEnrollmentForm, SessionRecordForm, enrollable_sessions,
)
from core.models import (
    Attendance, Course, CourseSession, Enrollment, Lesson, Module, Resource,
    MOIS, Payment, ResourceFeedback, RoleKey, SessionRecord,
    StudentSessionNote,
)

from .base import BusinessTestBase


class PedagogyTestBase(BusinessTestBase):
    def setUp(self):
        self.trainer_client = self.client_for(self.formateur)
        self.manager_client = self.client_for(self.peda)

    def record_payload(self, **overrides):
        payload = {
            'date': self.local_date(),
            'planned_start': '08:00',
            'planned_end': '10:00',
            'actual_start': '',
            'actual_end': '',
            'module': self.module.pk,
            'lesson': self.lesson.pk,
            'topic': 'Introduction au HTML',
            'objectives': 'Comprendre les balises',
            'content_covered': '',
            'content_remaining': '',
            'next_content': '',
            'exercises_done': '',
            'difficulties': '',
            'notes': '',
            'status': SessionRecord.Status.PLANNED,
        }
        payload.update(overrides)
        return payload

    def make_record(self, **kwargs):
        defaults = {
            'session': self.session,
            'module': self.module,
            'lesson': self.lesson,
            'date': self.today,
            'planned_start': dt_time(8, 0),
            'planned_end': dt_time(10, 0),
            'topic': 'Séance de test',
            'status': SessionRecord.Status.PLANNED,
            'recorded_by': self.formateur,
        }
        defaults.update(kwargs)
        return SessionRecord.objects.create(**defaults)

    def make_resource(self, **kwargs):
        defaults = {
            'title': 'Support de cours',
            'course': self.course,
            'kind': Resource.Kind.COURSE,
            'status': Resource.Status.PUBLISHED,
            'author': self.formateur,
            'html_content': '<p>Contenu</p>',
        }
        defaults.update(kwargs)
        return Resource.objects.create(**defaults)


class ProgramTests(PedagogyTestBase):
    def test_manager_can_add_a_course_from_the_program_page(self):
        response = self.manager_client.post(
            reverse('core:dashboard:course-create'),
            {
                'title': 'Anglais',
                'domain': 'Langues',
                'description': 'Anglais général',
                'duration_months': 6,
                'fee_amount': 120000,
                'monthly_fee_amount': 20000,
                'certificate_eligible': True,
            },
        )
        course = Course.objects.get(title='Anglais')
        self.assertRedirects(
            response,
            f'{reverse("core:dashboard:programs")}#formation-{course.pk}',
            fetch_redirect_response=False,
        )
        self.assertEqual(course.domain, 'Langues')
        self.assertTrue(course.active)
        self.assert_audited('COURSE_CREATE', course.pk)

    def test_manager_can_edit_a_course_without_changing_existing_tariffs(self):
        response = self.manager_client.post(
            reverse('core:dashboard:course-edit', args=[self.course.pk]),
            {
                'title': 'Informatique générale',
                'domain': 'Informatique',
                'description': 'Bureautique et bases',
                'duration_months': 4,
                'fee_amount': 160000,
                'monthly_fee_amount': 40000,
                'certificate_eligible': False,
            },
        )
        self.assertRedirects(
            response,
            f'{reverse("core:dashboard:programs")}#formation-{self.course.pk}',
            fetch_redirect_response=False,
        )
        self.course.refresh_from_db()
        self.enrollment.refresh_from_db()
        self.assertEqual(self.course.title, 'Informatique générale')
        self.assertEqual(self.course.monthly_fee_amount, 40000)
        self.assertEqual(self.enrollment.tariff_amount, 100000)
        self.assert_audited('COURSE_EDIT', self.course.pk)

    def test_manager_archives_and_restores_course_without_deleting_history(self):
        archive_url = reverse(
            'core:dashboard:course-archive', args=[self.course.pk])
        restore_url = reverse(
            'core:dashboard:course-restore', args=[self.course.pk])
        response = self.manager_client.post(archive_url)
        self.assertRedirects(
            response,
            f'{reverse("core:dashboard:programs")}?archives=1'
            f'#formation-{self.course.pk}',
            fetch_redirect_response=False,
        )
        self.course.refresh_from_db()
        self.assertFalse(self.course.active)
        self.assertTrue(CourseSession.objects.filter(pk=self.session.pk).exists())
        self.assertTrue(Enrollment.objects.filter(pk=self.enrollment.pk).exists())
        self.assertNotIn(
            self.session.pk,
            enrollable_sessions().values_list('pk', flat=True),
        )
        self.assertNotIn(
            self.session.pk,
            EnrollmentForm().fields['session'].queryset.values_list(
                'pk', flat=True),
        )
        self.assertNotIn(
            self.session.pk,
            NewEnrollmentForm().fields['session'].queryset.values_list(
                'pk', flat=True),
        )
        self.assertIn(
            self.session.pk,
            EnrollmentForm(instance=self.enrollment).fields[
                'session'
            ].queryset.values_list('pk', flat=True),
        )
        self.assertNotContains(
            self.manager_client.get(reverse('core:dashboard:programs')),
            'Développement Web',
        )
        self.assertContains(
            self.manager_client.get(
                reverse('core:dashboard:programs'), {'archives': '1'}),
            'Développement Web',
        )
        self.assert_audited('COURSE_ARCHIVE', self.course.pk)

        response = self.manager_client.post(restore_url)
        self.assertRedirects(
            response,
            f'{reverse("core:dashboard:programs")}#formation-{self.course.pk}',
            fetch_redirect_response=False,
        )
        self.course.refresh_from_db()
        self.assertTrue(self.course.active)
        self.assert_audited('COURSE_RESTORE', self.course.pk)

    def test_only_academic_managers_can_manage_courses(self):
        self.assertEqual(
            self.trainer_client.get(
                reverse('core:dashboard:course-create')).status_code,
            403,
        )
        self.assertEqual(
            self.client_for(self.secretaire).post(
                reverse('core:dashboard:course-edit', args=[self.course.pk]),
                {},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.manager_client.get(
                reverse('core:dashboard:course-archive',
                        args=[self.course.pk])).status_code,
            405,
        )

    def test_program_page_shows_course_management_actions_to_managers(self):
        response = self.manager_client.get(
            reverse('core:dashboard:programs'))
        self.assertContains(
            response, reverse('core:dashboard:course-create'))
        self.assertContains(
            response,
            reverse('core:dashboard:course-edit', args=[self.course.pk]),
        )
        self.assertContains(
            response,
            reverse('core:dashboard:course-archive', args=[self.course.pk]),
        )
        self.assertEqual(
            self.manager_client.get(
                reverse('core:dashboard:course-create')).status_code,
            200,
        )

    def test_manager_can_create_module_and_lesson(self):
        response = self.manager_client.post(
            reverse('core:dashboard:module-create'),
            {
                'course': self.course.pk,
                'title': 'Module CSS',
                'description': 'Mise en forme',
                'order': 2,
                'planned_hours': 15,
            },
        )
        self.assertRedirects(
            response,
            f'{reverse("core:dashboard:programs")}#formation-{self.course.pk}',
            fetch_redirect_response=False,
        )
        module = Module.objects.get(title='Module CSS')
        self.assert_audited('MODULE_CREATE', module.pk)

        response = self.manager_client.post(
            reverse('core:dashboard:lesson-create'),
            {
                'module': module.pk,
                'title': 'Sélecteurs CSS',
                'objectives': 'Savoir cibler les éléments',
                'order': 1,
                'planned_hours': 3,
            },
        )
        self.assertRedirects(
            response,
            f'{reverse("core:dashboard:programs")}#module-{module.pk}',
            fetch_redirect_response=False,
        )
        lesson = Lesson.objects.get(title='Sélecteurs CSS')
        self.assert_audited('LESSON_CREATE', lesson.pk)

    def test_trainer_can_create_module(self):
        response = self.trainer_client.post(
            reverse('core:dashboard:module-create'),
            {
                'course': self.course.pk,
                'title': 'Module JavaScript',
                'description': 'Interactivité côté client',
                'order': 3,
                'planned_hours': 12,
            },
        )
        self.assertRedirects(
            response,
            f'{reverse("core:dashboard:programs")}#formation-{self.course.pk}',
            fetch_redirect_response=False,
        )
        module = Module.objects.get(title='Module JavaScript')
        self.assertEqual(module.course, self.course)
        self.assert_audited('MODULE_CREATE', module.pk)

    def test_trainer_can_edit_module(self):
        module = Module.objects.create(
            course=self.course, title='Module v1', order=1, planned_hours=10,
        )
        response = self.trainer_client.post(
            reverse('core:dashboard:module-edit', args=[module.pk]),
            {
                'course': self.course.pk,
                'title': 'Module v2',
                'description': '',
                'order': 1,
                'planned_hours': 14,
            },
        )
        self.assertRedirects(
            response,
            f'{reverse("core:dashboard:programs")}#formation-{self.course.pk}',
            fetch_redirect_response=False,
        )
        module.refresh_from_db()
        self.assertEqual(module.title, 'Module v2')
        self.assertEqual(module.planned_hours, 14)
        self.assert_audited('MODULE_EDIT', module.pk)

    def test_trainer_sees_manage_buttons_on_programs(self):
        response = self.trainer_client.get(reverse('core:dashboard:programs'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, reverse('core:dashboard:module-create'))

    def test_formulaires_de_creation_sont_sur_la_page_programmes(self):
        """Le responsable pédagogique crée module et leçon sans quitter la page."""
        response = self.manager_client.get(reverse('core:dashboard:programs'))
        self.assertContains(
            response, f'action="{reverse("core:dashboard:module-create")}"')
        self.assertContains(
            response, f'action="{reverse("core:dashboard:lesson-create")}"')

    def test_formulaire_module_preselectionne_la_formation(self):
        response = self.manager_client.get(
            reverse('core:dashboard:module-create'),
            {'course': self.course.pk},
        )
        self.assertEqual(
            str(response.context['form']['course'].value()),
            str(self.course.pk),
        )

    def test_module_cree_sans_ordre_prend_la_suite(self):
        response = self.manager_client.post(
            reverse('core:dashboard:module-create'),
            {
                'course': self.course.pk,
                'title': 'Module sans ordre',
                'description': '',
                'order': '',
                'planned_hours': '',
            },
        )
        self.assertEqual(response.status_code, 302)
        module = Module.objects.get(title='Module sans ordre')
        self.assertEqual(module.order, self.module.order + 1)
        self.assertEqual(module.planned_hours, 0)
        self.assertEqual(
            response['Location'],
            f'{reverse("core:dashboard:programs")}#formation-{self.course.pk}',
        )

    def test_lecon_creee_sans_ordre_prend_la_suite(self):
        response = self.manager_client.post(
            reverse('core:dashboard:lesson-create'),
            {
                'module': self.module.pk,
                'title': 'Leçon sans ordre',
                'objectives': '',
                'order': '',
                'planned_hours': '',
            },
        )
        self.assertEqual(response.status_code, 302)
        lesson = Lesson.objects.get(title='Leçon sans ordre')
        self.assertEqual(lesson.order, self.lesson.order + 1)
        self.assertEqual(lesson.planned_hours, 0)
        self.assertIn(f'#module-{self.module.pk}', response['Location'])


class SessionRecordTests(PedagogyTestBase):
    def test_trainer_can_create_record_for_his_session(self):
        response = self.trainer_client.post(
            reverse('core:dashboard:session-record-create',
                    args=[self.session.pk]),
            self.record_payload(),
        )
        record = SessionRecord.objects.get()
        self.assertRedirects(
            response,
            reverse('core:dashboard:session-record-detail',
                    args=[record.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(record.session, self.session)
        self.assertEqual(record.recorded_by, self.formateur)
        self.assert_audited('SESSION_CREATE', record.pk)

    def test_trainer_cannot_create_record_for_another_session(self):
        other_session = CourseSession.objects.create(
            course=self.course,
            starts_at=self.today,
            ends_at=self.today + timedelta(days=30),
            status=CourseSession.Status.ACTIVE,
        )
        response = self.trainer_client.get(
            reverse('core:dashboard:session-record-create',
                    args=[other_session.pk]))
        self.assertEqual(response.status_code, 403)

    def test_record_detail_is_reserved_to_assigned_trainer(self):
        record = self.make_record()
        response = self.trainer_client.get(
            reverse('core:dashboard:session-record-detail',
                    args=[record.pk]))
        self.assertEqual(response.status_code, 200)

        other = self.make_user(RoleKey.FORMATEUR, 'formateur2@test.local')
        other_client = self.client_for(other)
        response = other_client.get(
            reverse('core:dashboard:session-record-detail',
                    args=[record.pk]))
        self.assertEqual(response.status_code, 403)

    def test_completed_record_requires_actual_start(self):
        form = SessionRecordForm(
            data=self.record_payload(
                status=SessionRecord.Status.COMPLETED,
                actual_start='',
                actual_end='10:00',
            ),
            session=self.session,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('actual_start', form.errors)

    def test_planned_end_must_follow_start(self):
        form = SessionRecordForm(
            data=self.record_payload(planned_end='07:00'),
            session=self.session,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('planned_end', form.errors)

    def test_lesson_must_belong_to_selected_module(self):
        other_module = Module.objects.create(
            course=self.course, title='Module JavaScript', order=3,
        )
        form = SessionRecordForm(
            data=self.record_payload(module=other_module.pk),
            session=self.session,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('lesson', form.errors)

    def test_record_update_is_audited(self):
        record = self.make_record()
        payload = self.record_payload(
            topic='Séance réalisée',
            status=SessionRecord.Status.COMPLETED,
            actual_start='08:05',
            actual_end='09:50',
            content_covered='Balises de base',
        )
        response = self.trainer_client.post(
            reverse('core:dashboard:session-record-detail',
                    args=[record.pk]),
            payload,
        )
        self.assertRedirects(
            response,
            reverse('core:dashboard:session-record-detail',
                    args=[record.pk]),
            fetch_redirect_response=False,
        )
        record.refresh_from_db()
        self.assertEqual(record.status, SessionRecord.Status.COMPLETED)
        self.assertEqual(record.topic, 'Séance réalisée')
        self.assert_audited('SESSION_UPDATE', record.pk)

    def test_trainer_sees_the_planning_shortcut(self):
        response = self.trainer_client.get(
            reverse('core:dashboard:session-records'))
        self.assertContains(response, 'Planifier une séance')
        self.assertContains(response, reverse(
            'core:dashboard:session-record-create', args=[self.session.id]))

    def test_secretary_reads_sessions_without_planning_shortcut(self):
        response = self.client_for(self.secretaire).get(
            reverse('core:dashboard:session-records'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Planifier une séance')
        self.assertNotContains(response, reverse(
            'core:dashboard:session-record-create', args=[self.session.id]))

    def test_admin_reads_sessions_without_planning_shortcut(self):
        response = self.client_for(self.admin).get(
            reverse('core:dashboard:session-records'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Planifier une séance')

    def test_duration_is_known_only_when_both_hours_are_set(self):
        record = self.make_record(
            planned_start=dt_time(8, 0), planned_end=dt_time(9, 30),
            actual_start=None, actual_end=None,
        )
        self.assertEqual(record.planned_minutes, 90)
        self.assertIsNone(record.actual_minutes)
        self.assertEqual(record.display_minutes, 90)

    def test_session_list_formats_duration_as_hours_and_minutes(self):
        self.make_record(planned_start=dt_time(16, 10), planned_end=dt_time(16, 15))
        response = self.trainer_client.get(
            reverse('core:dashboard:session-records'))
        self.assertContains(response, '0 h 05')
        self.assertNotContains(response, '0,08')


class AttendanceTests(PedagogyTestBase):
    def test_attendance_sheet_records_presence(self):
        record = self.make_record()
        response = self.trainer_client.post(
            reverse('core:dashboard:session-record-attendance',
                    args=[record.pk]),
            {
                f'status_{self.enrollment.pk}': Attendance.Status.LATE,
                f'arrival_{self.enrollment.pk}': '08:15',
                f'reason_{self.enrollment.pk}': '',
                f'note_{self.enrollment.pk}': 'Retard de transport',
            },
        )
        self.assertRedirects(
            response,
            reverse('core:dashboard:session-record-attendance',
                    args=[record.pk]),
            fetch_redirect_response=False,
        )
        attendance = Attendance.objects.get(enrollment=self.enrollment)
        self.assertEqual(attendance.status, Attendance.Status.LATE)
        self.assertEqual(attendance.arrival_time.strftime('%H:%M'), '08:15')
        self.assertEqual(attendance.session_record, record)
        self.assertEqual(attendance.recorded_by, self.formateur)
        self.assert_audited('ATTENDANCE_RECORD', record.pk)

    def test_invalid_status_is_ignored(self):
        record = self.make_record()
        self.trainer_client.post(
            reverse('core:dashboard:session-record-attendance',
                    args=[record.pk]),
            {f'status_{self.enrollment.pk}': 'INVENTE'},
        )
        self.assertEqual(Attendance.objects.count(), 0)

    def test_attendance_from_another_session_is_not_overwritten(self):
        day = self.today
        first = self.make_record(
            date=day,
            planned_start=dt_time(8, 0),
            planned_end=dt_time(10, 0),
        )
        second = self.make_record(
            date=day,
            planned_start=dt_time(10, 0),
            planned_end=dt_time(12, 0),
        )
        attendance = Attendance.objects.create(
            enrollment=self.enrollment,
            session_record=first,
            date=day,
            status=Attendance.Status.PRESENT,
            recorded_by=self.formateur,
        )
        self.trainer_client.post(
            reverse('core:dashboard:session-record-attendance',
                    args=[second.pk]),
            {f'status_{self.enrollment.pk}': Attendance.Status.ABSENT},
        )
        attendance.refresh_from_db()
        self.assertEqual(attendance.status, Attendance.Status.PRESENT)
        self.assertEqual(attendance.session_record, first)
        self.assertEqual(Attendance.objects.count(), 1)

    def test_secretary_can_read_but_not_edit_attendance(self):
        record = self.make_record()
        secretary_client = self.client_for(self.secretaire)
        url = reverse('core:dashboard:session-record-attendance',
                      args=[record.pk])
        response = secretary_client.get(url)
        self.assertEqual(response.status_code, 200)
        response = secretary_client.post(
            url, {f'status_{self.enrollment.pk}': Attendance.Status.PRESENT})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_attendance_history_filters(self):
        record = self.make_record()
        Attendance.objects.create(
            enrollment=self.enrollment, session_record=record,
            date=record.date, status=Attendance.Status.ABSENT,
            absence_reason='Maladie', recorded_by=self.formateur,
        )
        response = self.manager_client.get(
            reverse('core:dashboard:attendance-history'),
            {'status': Attendance.Status.ABSENT, 'q': 'Utilisateur'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['totals']['total'], 1)
        self.assertEqual(response.context['totals']['absents'], 1)

    def test_progression_page_supports_empty_session(self):
        response = self.manager_client.get(reverse('core:dashboard:progression'))
        self.assertEqual(response.status_code, 200)

    def test_progression_page_computes_hours(self):
        self.make_record(
            status=SessionRecord.Status.COMPLETED,
            actual_start=dt_time(8, 5),
            actual_end=dt_time(9, 55),
        )
        response = self.manager_client.get(reverse('core:dashboard:progression'))
        row = response.context['rows'][0]
        self.assertEqual(row['records'], 1)
        self.assertEqual(row['completed'], 1)
        self.assertEqual(row['planned_minutes'], 120)
        self.assertEqual(row['actual_minutes'], 110)
        self.assertEqual(row['remaining_minutes'], 10)
        self.assertIsNotNone(row['last_record'])
        self.assertContains(response, '2 h 00')
        self.assertContains(response, '1 h 50')
        self.assertNotContains(response, '1.83')
        self.assertNotContains(response, '1,83')


class ResourceTests(PedagogyTestBase):
    def test_published_resource_sets_publication_date(self):
        response = self.manager_client.post(
            reverse('core:dashboard:resource-create'),
            {
                'title': 'Introduction HTML',
                'description': 'Support du premier cours',
                'course': self.course.pk,
                'module': self.module.pk,
                'lesson': self.lesson.pk,
                'session': '',
                'kind': Resource.Kind.COURSE,
                'html_content': '<h1>Bonjour</h1>',
                'due_date': '',
                'status': Resource.Status.PUBLISHED,
            },
        )
        self.assertRedirects(
            response, reverse('core:dashboard:resources'),
            fetch_redirect_response=False,
        )
        resource = Resource.objects.get(title='Introduction HTML')
        self.assertEqual(resource.author, self.peda)
        self.assertIsNotNone(resource.published_at)
        self.assert_audited('RESOURCE_CREATE', resource.pk)

    def test_resource_requires_file_or_html(self):
        response = self.manager_client.post(
            reverse('core:dashboard:resource-create'),
            {
                'title': 'Ressource vide',
                'description': '',
                'course': self.course.pk,
                'module': '',
                'lesson': '',
                'session': '',
                'kind': Resource.Kind.COURSE,
                'html_content': '',
                'due_date': '',
                'status': Resource.Status.DRAFT,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Resource.objects.filter(title='Ressource vide').exists())

    def test_student_sees_only_published_resources_of_his_course(self):
        published = self.make_resource(title='Publié')
        self.make_resource(title='Brouillon', status=Resource.Status.DRAFT)
        other_course = Course.objects.create(
            title='Anglais', domain='Langues', fee_amount=50000,
        )
        self.make_resource(title='Autre cours', course=other_course)

        student_client = self.client_for(self.etudiant)
        response = student_client.get(reverse('core:dashboard:student-resources'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [r.pk for r in response.context['page'].object_list],
            [published.pk],
        )

    def test_student_parti_garde_les_anciennes_ressources_pas_les_nouvelles(self):
        date_depart = self.today - timedelta(days=1)
        self.enrollment.status = Enrollment.Status.COMPLETED
        self.enrollment.ended_at = date_depart
        self.enrollment.save(update_fields=['status', 'ended_at'])
        ancienne = self.make_resource(
            title='Publié avant le départ',
            session=self.session,
            published_at=timezone.now() - timedelta(days=2),
        )
        nouvelle = self.make_resource(
            title='Publié après le départ',
            session=self.session,
            published_at=timezone.now(),
        )

        client = self.client_for(self.etudiant)
        page = client.get(reverse('core:dashboard:student-resources'))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(
            [resource.pk for resource in page.context['page'].object_list],
            [ancienne.pk],
        )
        self.assertEqual(
            client.get(reverse(
                'core:dashboard:resource-view', args=[ancienne.pk]
            )).status_code,
            200,
        )
        self.assertEqual(
            client.get(reverse(
                'core:dashboard:resource-view', args=[nouvelle.pk]
            )).status_code,
            404,
        )

    def test_student_can_download_published_resource(self):
        resource = self.make_resource(
            title='Support PDF',
            file=SimpleUploadedFile('support.pdf', b'%PDF-1.4 contenu'),
        )
        student_client = self.client_for(self.etudiant)
        response = student_client.get(
            reverse('core:dashboard:resource-download', args=[resource.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            b''.join(response.streaming_content), b'%PDF-1.4 contenu')
        self.assert_audited('FILE_ACCESS', resource.pk)

    def test_student_cannot_download_draft_resource(self):
        resource = self.make_resource(
            title='Brouillon privé',
            status=Resource.Status.DRAFT,
            file=SimpleUploadedFile('brouillon.pdf', b'secret'),
        )
        student_client = self.client_for(self.etudiant)
        response = student_client.get(
            reverse('core:dashboard:resource-download', args=[resource.pk]))
        self.assertEqual(response.status_code, 404)

    def test_student_cannot_view_draft_resource(self):
        resource = self.make_resource(
            title='Brouillon HTML', status=Resource.Status.DRAFT)
        student_client = self.client_for(self.etudiant)
        response = student_client.get(
            reverse('core:dashboard:resource-view', args=[resource.pk]))
        self.assertEqual(response.status_code, 404)
        published = self.make_resource(title='Publié HTML')
        response = student_client.get(
            reverse('core:dashboard:resource-view', args=[published.pk]))
        self.assertEqual(response.status_code, 200)

    def test_trainer_only_sees_his_own_or_session_resources(self):
        own = self.make_resource(title='Mon support', author=self.formateur)
        self.make_resource(title='Support du responsable', author=self.peda)
        response = self.trainer_client.get(reverse('core:dashboard:resources'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [r.pk for r in response.context['page'].object_list], [own.pk]
        )

    def test_other_trainer_cannot_edit_resource(self):
        resource = self.make_resource(title='Protégé', author=self.formateur)
        other = self.make_user(RoleKey.FORMATEUR, 'formateur3@test.local')
        other_client = self.client_for(other)
        response = other_client.get(
            reverse('core:dashboard:resource-edit', args=[resource.pk]))
        self.assertEqual(response.status_code, 403)

    def test_student_attendance_lists_only_his_records(self):
        record = self.make_record()
        Attendance.objects.create(
            enrollment=self.enrollment, session_record=record,
            date=record.date, status=Attendance.Status.PRESENT,
            recorded_by=self.formateur,
        )
        other_student = self.make_user(
            RoleKey.ETUDIANT, 'etudiant5@test.local')
        other_enrollment = Enrollment.objects.create(
            student=other_student, session=self.session,
            status=Enrollment.Status.ACTIVE, net_amount=50000,
        )
        Attendance.objects.create(
            enrollment=other_enrollment, session_record=record,
            date=record.date, status=Attendance.Status.ABSENT,
            recorded_by=self.formateur,
        )
        student_client = self.client_for(self.etudiant)
        response = student_client.get(reverse('core:dashboard:student-attendance'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [a.enrollment_id for a in response.context['page'].object_list],
            [self.enrollment.pk],
        )
        self.assertEqual(response.context['totals']['total'], 1)


class StudentDashboardTests(PedagogyTestBase):
    def test_dashboard_affiche_le_reste_par_mensualite(self):
        Payment.objects.create(
            enrollment=self.enrollment,
            amount=10000,
            method=Payment.Method.CASH,
            motif=Payment.Motif.MONTHLY,
            period_year=self.today.year,
            period_month=self.today.month,
            status=Payment.Status.COMPLETED,
            recorded_by=self.assistant,
        )

        response = self.client_for(self.etudiant).get(
            reverse('core:dashboard:etudiant-dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_due'], self.enrollment.total_due)
        ligne = next(
            ligne for ligne in response.context['monthly_situation']
            if ligne['year'] == self.today.year
            and ligne['month'] == dict(MOIS)[self.today.month]
        )
        self.assertEqual(ligne['due'], 30000)
        self.assertEqual(ligne['paid'], 10000)
        self.assertEqual(ligne['remaining'], 20000)


class StudentNotebookTests(PedagogyTestBase):
    """Fiche de cours remplie par l'apprenant après chaque séance."""

    def setUp(self):
        super().setUp()
        self.student_client = self.client_for(self.etudiant)
        self.record = self.make_record(
            status=SessionRecord.Status.COMPLETED,
            actual_start=dt_time(8, 0),
            actual_end=dt_time(10, 0),
            content_covered='Les balises de base',
        )

    def note_payload(self, **overrides):
        payload = {
            'notions_learned': 'Balises html, head et body',
            'difficulties': '',
            'observations': '',
            'attended': 'on',
            'followed_start': '08:00',
            'followed_end': '10:00',
        }
        payload.update(overrides)
        return payload

    def test_notebook_lists_completed_record(self):
        response = self.student_client.get(
            reverse('core:dashboard:student-notebook'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['stats']['total'], 1)
        self.assertEqual(response.context['stats']['missing'], 1)

    def test_student_can_fill_note(self):
        url = reverse('core:dashboard:student-note', args=[self.record.id])
        response = self.student_client.post(url, self.note_payload())
        self.assertRedirects(
            response, reverse('core:dashboard:student-notebook'))
        note = StudentSessionNote.objects.get(
            enrollment=self.enrollment, session_record=self.record)
        self.assertTrue(note.attended)
        self.assertEqual(note.followed_start, dt_time(8, 0))
        self.assertEqual(note.followed_end, dt_time(10, 0))
        self.assert_audited('STUDENT_NOTE_CREATE')

    def test_end_must_follow_start(self):
        url = reverse('core:dashboard:student-note', args=[self.record.id])
        response = self.student_client.post(
            url, self.note_payload(followed_start='10:00', followed_end='08:00'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(StudentSessionNote.objects.exists())
        self.assertContains(
            response, "heure de fin suivie doit")

    def test_planned_record_redirects(self):
        planned = self.make_record(
            status=SessionRecord.Status.PLANNED,
            planned_start=dt_time(14, 0), planned_end=dt_time(16, 0))
        url = reverse('core:dashboard:student-note', args=[planned.id])
        response = self.student_client.get(url)
        self.assertRedirects(
            response, reverse('core:dashboard:student-notebook'))
        self.assertFalse(StudentSessionNote.objects.exists())

    def test_cannot_fill_note_for_foreign_session(self):
        other = self.make_user(RoleKey.ETUDIANT, 'etudiant9@test.local')
        url = reverse('core:dashboard:student-note', args=[self.record.id])
        self.assertEqual(self.client_for(other).get(url).status_code, 404)

    def test_elevated_user_blocked_from_notebook(self):
        response = self.client_for(self.admin).get(
            reverse('core:dashboard:student-notebook'))
        self.assertEqual(response.status_code, 403)


class StudentCourseSheetTests(PedagogyTestBase):
    """Feuille de suivi imprimable de l'apprenant."""

    def setUp(self):
        super().setUp()
        self.student_client = self.client_for(self.etudiant)
        record = self.make_record(
            status=SessionRecord.Status.COMPLETED,
            actual_start=dt_time(8, 0),
            actual_end=dt_time(10, 0),
        )
        StudentSessionNote.objects.create(
            enrollment=self.enrollment, session_record=record,
            notions_learned='Balises html', attended=True,
            followed_start=dt_time(8, 0), followed_end=dt_time(10, 0),
        )
        self.url = reverse(
            'core:dashboard:student-course-sheet', args=[self.session.id])

    def test_owner_can_view_sheet(self):
        response = self.student_client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Feuille de suivi")
        self.assertContains(response, "Balises html")

    def test_sheet_is_owner_only(self):
        other = self.make_user(RoleKey.ETUDIANT, 'etudiant8@test.local')
        self.assertEqual(self.client_for(other).get(self.url).status_code, 404)

    def test_trainer_cannot_view_student_sheet(self):
        self.assertEqual(self.trainer_client.get(self.url).status_code, 403)


class TextbookPrintTests(PedagogyTestBase):
    """Cahier de texte imprimable du formateur."""

    def test_trainer_can_print_textbook(self):
        self.make_record(
            status=SessionRecord.Status.COMPLETED,
            actual_start=dt_time(8, 0), actual_end=dt_time(10, 0))
        url = reverse(
            'core:dashboard:textbook-print', args=[self.session.id])
        response = self.trainer_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cahier de texte")
        self.assertContains(response, "2 h 00")

    def test_student_cannot_print_textbook(self):
        url = reverse(
            'core:dashboard:textbook-print', args=[self.session.id])
        response = self.client_for(self.etudiant).get(url)
        self.assertEqual(response.status_code, 403)


class CourseSessionGroupTests(PedagogyTestBase):
    """Écran Groupes : création, édition et périmètre de lecture."""

    def group_payload(self, **overrides):
        payload = {
            'name': 'Groupe Web du matin',
            'course': self.course.id,
            'starts_at': self.local_date(1),
            'ends_at': self.local_date(30),
            'schedule': 'Lun-Ven 13h-15h',
            'capacity': 25,
            'status': CourseSession.Status.PLANNED,
            'formateurs': [self.formateur.id],
        }
        payload.update(overrides)
        return payload

    def test_resp_peda_and_direction_can_create_group(self):
        for user in (self.peda, self.direction):
            with self.subTest(role=user.primary_role):
                client = self.client_for(user)
                before = CourseSession.objects.count()
                response = client.post(
                    reverse('core:dashboard:course-session-create'),
                    self.group_payload(schedule='Mar-Jeu 09h-11h'),
                )
                self.assertRedirects(
                    response,
                    reverse('core:dashboard:course-sessions'),
                    fetch_redirect_response=False,
                )
                self.assertEqual(CourseSession.objects.count(), before + 1)
                group = CourseSession.objects.get(schedule='Mar-Jeu 09h-11h')
                self.assertEqual(group.capacity, 25)
                self.assertIn(self.formateur, group.formateurs.all())
                self.assert_audited('COURSE_SESSION_CREATE', group.pk)
                group.delete()

    def test_formateur_cannot_create_group(self):
        response = self.trainer_client.get(
            reverse('core:dashboard:course-session-create'))
        self.assertEqual(response.status_code, 403)

    def test_admin_roles_can_create_group(self):
        for user in (self.super_admin, self.admin):
            with self.subTest(role=user.primary_role):
                client = self.client_for(user)
                response = client.post(
                    reverse('core:dashboard:course-session-create'),
                    self.group_payload(name=f"Groupe {user.primary_role}"),
                )
                self.assertRedirects(
                    response,
                    reverse('core:dashboard:course-sessions'),
                    fetch_redirect_response=False,
                )
                group = CourseSession.objects.get(
                    name=f"Groupe {user.primary_role}")
                self.assertIn(self.formateur, group.formateurs.all())

    def test_end_before_start_is_rejected(self):
        before = CourseSession.objects.count()
        response = self.manager_client.post(
            reverse('core:dashboard:course-session-create'),
            self.group_payload(
                starts_at=self.local_date(30), ends_at=self.local_date(1)),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CourseSession.objects.count(), before)
        self.assertContains(response, "date de fin doit suivre")

    def test_authorized_roles_can_list_groups(self):
        for user in (
            self.super_admin, self.admin, self.peda, self.direction,
            self.formateur, self.secretaire,
        ):
            with self.subTest(role=user.primary_role):
                client = self.client_for(user)
                self.assertEqual(
                    client.get(
                        reverse('core:dashboard:course-sessions')
                    ).status_code,
                    200,
                )

    def test_student_cannot_list_groups(self):
        self.assertEqual(
            self.client_for(self.etudiant).get(
                reverse('core:dashboard:course-sessions')).status_code,
            403,
        )

    def test_formateur_sees_only_own_groups(self):
        other = CourseSession.objects.create(
            course=self.course,
            starts_at=self.today + timedelta(days=5),
            ends_at=self.today + timedelta(days=40),
            schedule='Sam 08h-12h',
            capacity=10,
            status=CourseSession.Status.PLANNED,
        )
        response = self.trainer_client.get(
            reverse('core:dashboard:course-sessions'))
        listed = [s.id for s in response.context['page']]
        self.assertIn(self.session.id, listed)
        self.assertNotIn(other.id, listed)

    def test_resp_peda_can_edit_group(self):
        url = reverse(
            'core:dashboard:course-session-edit', args=[self.session.id])
        response = self.manager_client.post(url, self.group_payload(
            schedule='Lun-Ven 08h-10h',
            capacity=42,
            status=CourseSession.Status.ACTIVE,
            formateurs=[self.formateur.id],
        ))
        self.assertRedirects(
            response,
            reverse('core:dashboard:course-sessions'),
            fetch_redirect_response=False,
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.capacity, 42)
        self.assertEqual(self.session.status, CourseSession.Status.ACTIVE)
        self.assert_audited('COURSE_SESSION_EDIT', self.session.pk)

    def test_group_without_trainer_is_refused(self):
        """Un groupe qui va enseigner sans formateur ne se crée pas."""
        before = CourseSession.objects.count()
        response = self.manager_client.post(
            reverse('core:dashboard:course-session-create'),
            self.group_payload(formateurs=[]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CourseSession.objects.count(), before)
        self.assertContains(response, "au moins un formateur")

    def test_removing_the_last_trainer_is_refused(self):
        """Retirer le seul formateur d'un groupe en cours est le même vide."""
        url = reverse(
            'core:dashboard:course-session-edit', args=[self.session.id])
        response = self.manager_client.post(url, self.group_payload(
            status=CourseSession.Status.ACTIVE, formateurs=[],
        ))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "au moins un formateur")
        self.session.refresh_from_db()
        self.assertIn(self.formateur, self.session.formateurs.all())

    def test_completed_group_may_stay_without_trainer(self):
        """Une archive reprise des classeurs reste modifiable sans affectation."""
        url = reverse(
            'core:dashboard:course-session-edit', args=[self.session.id])
        response = self.manager_client.post(url, self.group_payload(
            status=CourseSession.Status.COMPLETED, formateurs=[],
        ))
        self.assertRedirects(
            response,
            reverse('core:dashboard:course-sessions'),
            fetch_redirect_response=False,
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, CourseSession.Status.COMPLETED)
        self.assertEqual(self.session.formateurs.count(), 0)

    def test_admin_form_applies_the_same_rule(self):
        """La porte Django Admin ne crée pas ce que l'écran Groupes refuse."""
        form = FormuleGroupeAdmin(data={
            'name': 'Groupe sans formateur',
            'course': self.course.pk,
            'starts_at': self.local_date(1),
            'ends_at': self.local_date(30),
            'schedule': 'Lun-Ven 13h-15h',
            'capacity': 25,
            'status': CourseSession.Status.PLANNED,
            'formateurs': [],
        })
        self.assertFalse(form.is_valid())
        self.assertIn('formateurs', form.errors)


class ResourceFeedbackTests(PedagogyTestBase):
    """Retour de l'étudiant sur une ressource publiée."""

    def setUp(self):
        super().setUp()
        self.resource = self.make_resource()
        self.feedback_url = reverse(
            'core:dashboard:resource-feedback', args=[self.resource.pk])
        self.view_url = reverse(
            'core:dashboard:resource-view', args=[self.resource.pk])
        self.student_client = self.client_for(self.etudiant)

    def feedback_payload(self, **overrides):
        payload = {'rating': '4', 'comment': 'Très clair, merci.'}
        payload.update(overrides)
        return payload

    def test_student_can_post_feedback(self):
        response = self.student_client.post(
            self.feedback_url, self.feedback_payload())
        self.assertRedirects(
            response, self.view_url, fetch_redirect_response=False)
        feedback = ResourceFeedback.objects.get(
            resource=self.resource, student=self.etudiant)
        self.assertEqual(feedback.rating, 4)
        self.assertEqual(feedback.comment, 'Très clair, merci.')
        self.assert_audited('RESOURCE_FEEDBACK', self.resource.pk)

    def test_student_updates_own_feedback_instead_of_duplicating(self):
        self.student_client.post(self.feedback_url, self.feedback_payload())
        self.student_client.post(self.feedback_url, self.feedback_payload(
            rating='5', comment='Finalement excellent.'))
        rows = ResourceFeedback.objects.filter(
            resource=self.resource, student=self.etudiant)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().rating, 5)
        self.assertEqual(rows.get().comment, 'Finalement excellent.')

    def test_feedback_requires_rating_or_comment(self):
        response = self.student_client.post(
            self.feedback_url, {'rating': '', 'comment': ''})
        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response, "Donnez une note", status_code=400)
        self.assertFalse(ResourceFeedback.objects.exists())

    def test_trainer_sees_student_feedback(self):
        self.student_client.post(self.feedback_url, self.feedback_payload())
        response = self.trainer_client.get(self.view_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Très clair, merci.')
        self.assertContains(response, '4 / 5')

    def test_admin_and_super_admin_see_feedback_readonly(self):
        self.student_client.post(self.feedback_url, self.feedback_payload())
        for user in (self.admin, self.super_admin):
            with self.subTest(role=user.primary_role):
                client = self.client_for(user)
                response = client.get(self.view_url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Très clair, merci.')
                self.assertEqual(
                    client.post(
                        self.feedback_url, self.feedback_payload()).status_code,
                    403,
                )

    def test_trainer_cannot_post_feedback(self):
        response = self.trainer_client.post(
            self.feedback_url, self.feedback_payload())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ResourceFeedback.objects.exists())

    def test_student_cannot_feedback_on_foreign_resource(self):
        other_course = Course.objects.create(
            title='Espagnol', domain='Langues', fee_amount=50000,
        )
        foreign = self.make_resource(title='Cours espagnol', course=other_course)
        url = reverse('core:dashboard:resource-feedback', args=[foreign.pk])
        response = self.student_client.post(url, self.feedback_payload())
        self.assertEqual(response.status_code, 404)
        self.assertFalse(ResourceFeedback.objects.exists())
