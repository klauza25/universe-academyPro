"""Tests de l'année académique : le calendrier posé par la direction et ses filtres."""
import datetime as dt

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from core import annee_academique as aa
from core.forms import AcademicYearForm
from core.models import (
    AcademicYear, CourseSession, Enrollment, Payment, RoleKey, User,
)

from .base import BusinessTestBase


class AnneeAcademiqueBase(BusinessTestBase):
    """Une année qui couvre le groupe de test, une année qui ne couvre rien.

    Le groupe de la base commune démarre 30 jours avant aujourd'hui : la fenêtre
    « en cours » l'englobe, la fenêtre 1999-2000 laisse tout dehors.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.annee_courante = AcademicYear.objects.create(
            label='2026-2027',
            start_date=cls.today - dt.timedelta(days=60),
            end_date=cls.today + dt.timedelta(days=300),
            is_current=True,
        )
        cls.annee_vide = AcademicYear.objects.create(
            label='1999-2000',
            start_date=dt.date(1999, 1, 1),
            end_date=dt.date(2000, 12, 31),
        )

    @staticmethod
    def _etudiants():
        return User.objects.filter(roles__key=RoleKey.ETUDIANT)


class AnneeAcademiqueModeleTest(AnneeAcademiqueBase):
    def test_cocher_une_annee_decoche_la_precedente(self):
        suivante = AcademicYear(
            label='2027-2028',
            start_date=self.today + dt.timedelta(days=301),
            end_date=self.today + dt.timedelta(days=700),
            is_current=True,
        )
        suivante.save()
        self.annee_courante.refresh_from_db()
        self.assertFalse(self.annee_courante.is_current)
        self.assertEqual(
            list(AcademicYear.objects.filter(is_current=True)
                 .values_list('label', flat=True)), ['2027-2028'])

    def test_le_service_designe_l_annee_en_cours(self):
        self.assertEqual(aa.en_cours(), self.annee_courante)

    def test_deux_annees_en_cours_sont_refusees_en_base(self):
        """Passer devant `save()` ne fait pas sauter la garde."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AcademicYear.objects.filter(pk=self.annee_vide.pk).update(
                    is_current=True)

    def test_le_dernier_jour_doit_suivre_le_premier(self):
        annee = AcademicYear(
            label='2031-retro',
            start_date=self.today,
            end_date=self.today - dt.timedelta(days=1),
        )
        with self.assertRaises(ValidationError):
            annee.full_clean()

    def test_une_fenetre_incoherente_est_refusee_en_base(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AcademicYear.objects.create(
                    label='2030-retro',
                    start_date=dt.date(2030, 1, 1),
                    end_date=dt.date(2029, 12, 31),
                )

    def test_deux_annees_ne_peuvent_pas_porter_le_meme_libelle(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AcademicYear.objects.create(
                    label='2026-2027',
                    start_date=dt.date(2026, 1, 1),
                    end_date=dt.date(2026, 12, 31),
                )

    def test_couvre_reconnait_une_date_de_la_fenetre(self):
        self.assertTrue(self.annee_courante.couvre(self.today))
        self.assertFalse(self.annee_courante.couvre(dt.date(1999, 6, 1)))


class AnneeAcademiqueServiceTest(AnneeAcademiqueBase):
    def test_sans_annee_posee_rien_n_est_filtre(self):
        AcademicYear.objects.all().delete()
        self.assertIsNone(aa.en_cours())
        self.assertIsNone(aa.resoudre(''))
        groupes = CourseSession.objects.all()
        self.assertEqual(aa.fil_groupes(groupes, None).count(), groupes.count())
        self.assertEqual(
            aa.fil_etudiants(self._etudiants(), None).count(),
            self._etudiants().count())

    def test_toutes_les_annees_ne_filtrent_rien(self):
        self.assertIsNone(aa.resoudre(aa.TOUTES))

    def test_resoudre_retombe_sur_l_annee_en_cours(self):
        self.assertEqual(aa.resoudre(''), self.annee_courante)
        self.assertEqual(aa.resoudre('pas-un-identifiant'), self.annee_courante)
        self.assertEqual(
            aa.resoudre('00000000-0000-0000-0000-000000000000'),
            self.annee_courante)

    def test_resoudre_reconnait_une_annee_designee(self):
        self.assertEqual(aa.resoudre(str(self.annee_vide.pk)), self.annee_vide)

    def test_les_groupes_se_choisissent_sur_la_date_de_debut(self):
        self.assertEqual(
            aa.fil_groupes(CourseSession.objects.all(),
                           self.annee_courante).count(), 1)
        self.assertEqual(
            aa.fil_groupes(CourseSession.objects.all(),
                           self.annee_vide).count(), 0)

    def test_les_inscriptions_suivent_la_fenetre_du_groupe(self):
        self.assertEqual(
            aa.fil_inscriptions(Enrollment.objects.all(),
                                self.annee_courante).count(), 1)
        self.assertEqual(
            aa.fil_inscriptions(Enrollment.objects.all(),
                                self.annee_vide).count(), 0)

    def test_une_inscription_annulee_ne_place_personne_dans_l_annee(self):
        self.enrollment.status = Enrollment.Status.CANCELLED
        self.enrollment.save(update_fields=['status'])
        self.assertEqual(
            aa.fil_inscriptions(Enrollment.objects.all(),
                                self.annee_courante).count(), 0)
        self.assertEqual(
            aa.fil_etudiants(self._etudiants(), self.annee_courante).count(), 0)

    def test_un_etudiant_inscrit_deux_fois_n_est_compte_qu_une_fois(self):
        seconde = CourseSession.objects.create(
            course=self.course,
            starts_at=self.today - dt.timedelta(days=10),
            ends_at=self.today + dt.timedelta(days=80),
            status=CourseSession.Status.ACTIVE,
        )
        Enrollment.objects.create(
            student=self.etudiant, session=seconde,
            status=Enrollment.Status.COMPLETED,
        )
        self.assertEqual(
            aa.fil_etudiants(self._etudiants(), self.annee_courante).count(), 1)

    def test_un_etudiant_sans_inscription_n_est_d_aucune_annee(self):
        orphelin = self.make_user(RoleKey.ETUDIANT, 'orphelin@test.local')
        self.assertIn(orphelin, self._etudiants())
        self.assertNotIn(
            orphelin, aa.fil_etudiants(self._etudiants(), self.annee_courante))
        self.assertIn(
            orphelin, aa.fil_etudiants(self._etudiants(), None))

    def test_le_drapeau_nomme_l_annee_filtree(self):
        self.assertIn('2026-2027', str(aa.drapeau(self.annee_courante)))

    def test_le_drapeau_signale_l_absence_d_annee(self):
        self.assertIn('Aucune année', str(aa.drapeau(None)))


class AnneeAcademiqueFiltresEcransTest(AnneeAcademiqueBase):
    """Les quatre écrans filtrés ne montrent que l'année posée par la direction.

    Le sélecteur est le même partout : l'année en cours par défaut, une autre
    année de la liste, ou « Toutes les années » quand on veut tout revoir.
    """

    def setUp(self):
        self.secretariat = self.client_for(self.secretaire)
        self.caisse = self.client_for(self.assistant)
        self.peda_client = self.client_for(self.peda)

    def test_le_secretaire_voit_l_etudiant_de_l_annee_en_cours(self):
        page = self.secretariat.get(reverse('core:dashboard:student-list'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'etudiant@test.local')
        self.assertIn(self.etudiant, page.context['page'])

    def test_une_annee_sans_inscription_vide_la_liste(self):
        page = self.secretariat.get(
            reverse('core:dashboard:student-list'),
            {'annee_academique': self.annee_vide.pk})
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'etudiant@test.local')
        self.assertEqual(len(page.context['page']), 0)

    def test_toutes_les_annees_remplacent_le_filtre(self):
        page = self.secretariat.get(
            reverse('core:dashboard:student-list'),
            {'annee_academique': aa.TOUTES})
        self.assertContains(page, 'etudiant@test.local')

    def test_le_selecteur_nomme_chaque_annee_posee(self):
        page = self.secretariat.get(reverse('core:dashboard:student-list'))
        self.assertContains(page, 'Toutes les années')
        self.assertContains(page, '1999-2000')
        self.assertContains(page, f'value="{self.annee_vide.pk}"')

    def test_le_bandeau_nomme_l_annee_appliquee(self):
        page = self.secretariat.get(reverse('core:dashboard:student-list'))
        self.assertContains(page, 'Année académique 2026-2027')

    def test_la_liste_des_groupes_suiv_l_annee(self):
        page = self.peda_client.get(reverse('core:dashboard:course-sessions'))
        self.assertIn(self.session, page.context['page'])
        hors = self.peda_client.get(
            reverse('core:dashboard:course-sessions'),
            {'annee_academique': self.annee_vide.pk})
        self.assertNotIn(self.session, hors.context['page'])
        toutes = self.peda_client.get(
            reverse('core:dashboard:course-sessions'),
            {'annee_academique': aa.TOUTES})
        self.assertIn(self.session, toutes.context['page'])

    def test_le_guichet_ne_propose_que_les_dossiers_de_l_annee(self):
        url = reverse('core:dashboard:payment-create')
        dans = self.caisse.get(
            url, {'student': self.etudiant.pk,
                  'annee_academique': self.annee_courante.pk})
        self.assertContains(dans, f'value="{self.enrollment.pk}"')
        hors = self.caisse.get(
            url, {'student': self.etudiant.pk,
                  'annee_academique': self.annee_vide.pk})
        self.assertNotContains(hors, f'value="{self.enrollment.pk}"')

    def test_un_compte_sans_inscription_reste_disponible_au_guichet(self):
        """L'inscription depuis le guichet ne dépend pas de l'année filtrée."""
        self.make_user(RoleKey.ETUDIANT, 'orphelin@test.local')
        page = self.caisse.get(reverse('core:dashboard:payment-create'))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'Comptes étudiants sans inscription')
        self.assertEqual(list(page.context['students_without_enrollment']), [])
        toutes = self.caisse.get(
            reverse('core:dashboard:payment-create'),
            {'annee_academique': aa.TOUTES})
        self.assertContains(toutes, 'orphelin@test.local')
        self.assertNotContains(toutes, 'Comptes étudiants sans inscription')

    def test_la_grille_des_mois_ne_propose_que_les_dossiers_de_l_annee(self):
        url = reverse('core:dashboard:payment-months')
        dans = self.caisse.get(
            url, {'student': self.etudiant.pk,
                  'annee_academique': self.annee_courante.pk})
        self.assertContains(dans, f'value="{self.enrollment.pk}"')
        hors = self.caisse.get(
            url, {'student': self.etudiant.pk,
                  'annee_academique': self.annee_vide.pk})
        self.assertNotContains(hors, f'value="{self.enrollment.pk}"')

    def test_l_encaissement_des_mois_garde_l_annee_choisie(self):
        page = self.caisse.post(
            reverse('core:dashboard:payment-months')
            + f'?annee_academique={self.annee_courante.pk}',
            {'annee': str(self.today.year), 'enrollment': self.enrollment.pk,
             'method': Payment.Method.CASH, 'account': self.cash.pk,
             'mois': [str(self.today.month)],
             f'montant_{self.today.month}': '30000', 'note': '',
             'submission_key': 'calendar-filter-payment'})
        self.assertEqual(page.status_code, 302)
        self.assertIn('annee_academique', page['Location'])
        self.assertIn(str(self.annee_courante.pk), page['Location'])
        self.assertEqual(
            Payment.objects.get(period_month=self.today.month).amount, 30000)

    def test_le_bandeau_avertit_quand_aucune_annee_n_est_posee(self):
        AcademicYear.objects.all().delete()
        page = self.caisse.get(reverse('core:dashboard:payment-create'))
        self.assertContains(page, 'Aucune année académique définie')
        grille = self.caisse.get(reverse('core:dashboard:payment-months'))
        self.assertContains(grille, 'Aucune année académique définie')


class AnneeAcademiqueEcranTest(AnneeAcademiqueBase):
    def setUp(self):
        self.client = self.client_for(self.direction)

    def payload(self, **surcharge):
        data = {
            'label': '2025-2026',
            'start_date': (self.today - dt.timedelta(days=400)).strftime('%Y-%m-%d'),
            'end_date': (self.today - dt.timedelta(days=61)).strftime('%Y-%m-%d'),
        }
        data.update(surcharge)
        return data

    def test_la_direction_pose_une_annee(self):
        page = self.client.post(
            reverse('core:dashboard:academic-years'), self.payload())
        self.assertRedirects(
            page, reverse('core:dashboard:academic-years'),
            fetch_redirect_response=False)
        annee = AcademicYear.objects.get(label='2025-2026')
        self.assertFalse(annee.is_current)
        self.annee_courante.refresh_from_db()
        self.assertTrue(self.annee_courante.is_current)

    def test_cocher_l_annee_laisse_sa_trace_dans_le_journal(self):
        page = self.client.post(
            reverse('core:dashboard:academic-years'),
            self.payload(
                label='2027-2028', is_current='on',
                start_date=(self.today + dt.timedelta(days=301)).strftime('%Y-%m-%d'),
                end_date=(self.today + dt.timedelta(days=700)).strftime('%Y-%m-%d')))
        self.assertEqual(page.status_code, 302)
        annee = AcademicYear.objects.get(label='2027-2028')
        entree = self.assert_audited('ACADEMIC_YEAR_CREATE', annee.pk)
        self.assertTrue(entree.after_summary['en_cours'])
        self.assertEqual(entree.after_summary['decochee'], '2026-2027')

    def test_une_fenetre_incoherente_est_refusee_ecran_par_ecran(self):
        page = self.client.post(
            reverse('core:dashboard:academic-years'),
            self.payload(label='2030-retro', start_date='2030-01-01',
                         end_date='2029-12-31'))
        self.assertEqual(page.status_code, 200)
        self.assertFalse(AcademicYear.objects.filter(label='2030-retro').exists())

    def test_le_reglage_d_une_annee_est_historise(self):
        page = self.client.post(
            reverse('core:dashboard:academic-year-update',
                    args=[self.annee_courante.pk]),
            {'label': '2026-2027', 'start_date': '2026-09-01',
             'end_date': '2027-08-31', 'is_current': 'on'})
        self.assertRedirects(
            page, reverse('core:dashboard:academic-years'),
            fetch_redirect_response=False)
        entree = self.assert_audited('ACADEMIC_YEAR_EDIT', self.annee_courante.pk)
        self.assertEqual(
            entree.before_summary['debut'],
            str(self.today - dt.timedelta(days=60)))
        self.assertEqual(entree.after_summary['debut'], '2026-09-01')

    def test_la_liste_des_annees_affiche_ce_que_chacune_couvre(self):
        page = self.client.get(reverse('core:dashboard:academic-years'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '2026-2027')
        self.assertContains(page, '1999-2000')

    def test_le_bandeau_avertit_quand_aucune_annee_n_est_posee(self):
        AcademicYear.objects.all().delete()
        page = self.client.get(reverse('core:dashboard:academic-years'))
        self.assertContains(page, 'Aucune année académique définie')

    def test_l_administrateur_transversal_consulte_et_regle(self):
        client = self.client_for(self.super_admin)
        self.assertEqual(
            client.get(reverse('core:dashboard:academic-years')).status_code, 200)
        self.assertEqual(
            client.post(reverse('core:dashboard:academic-years'),
                        self.payload(label='2024-2025')).status_code, 302)

    def test_le_calendrier_est_refuse_au_secretaire(self):
        client = self.client_for(self.secretaire)
        self.assertEqual(
            client.get(reverse('core:dashboard:academic-years')).status_code, 403)
        self.assertEqual(
            client.post(reverse('core:dashboard:academic-years'),
                        self.payload()).status_code, 403)

    def test_le_calendrier_se_consulte_dans_django_admin_sans_se_modifier_ici(self):
        enregistre = admin.site._registry[AcademicYear]
        self.assertFalse(enregistre.has_add_permission(None))
        self.assertFalse(enregistre.has_change_permission(None))
        self.assertFalse(enregistre.has_delete_permission(None))


class AnneeAcademiqueFormulaireTest(AnneeAcademiqueBase):
    def test_le_formulaire_releve_la_garde_du_modele(self):
        forme = AcademicYearForm(data={
            'label': '2031-retro', 'start_date': '2031-01-01',
            'end_date': '2030-12-31',
        })
        self.assertFalse(forme.is_valid())
        self.assertIn('end_date', forme.errors)

    def test_le_formulaire_accepte_une_fenetre_coherente(self):
        forme = AcademicYearForm(data={
            'label': '2031-2032', 'start_date': '2031-01-01',
            'end_date': '2032-12-31', 'is_current': 'on',
        })
        self.assertTrue(forme.is_valid(), forme.errors)
