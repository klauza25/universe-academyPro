"""Aucun mélange de langue : rendu anglais contrôlé page par page.

`verifier_i18n` garantit que le code est balisé et traduit ; ce test garantit le
rendu. Il parcourt les neuf tableaux de bord et les pages publiques en anglais,
puis refuse toute chrome française encore visible. Le contenu saisi par les
agents (intitulés d'inscription, caisses, catégories, motifs de visite, libellés
de rôles stockés en base) reste en français : il est retiré du texte analysé.
"""

import datetime as dt
import re

from django.contrib.auth import get_user_model
from django.template.loader import get_template
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    AcademicYear, CashAccount, CashTransaction, Course, CourseSession, Lesson,
    Module, Payment, PlatformSetting, Role, RoleKey, ROLES_DISSOUS,
    TransactionCategory, VisitReason,
)
from core.tests.base import BusinessTestBase
from core import i18n_tools

User = get_user_model()

COMMENTAIRE_RE = re.compile(r'<!--.*?-->', re.DOTALL)
STYLE_RE = re.compile(r'<style.*?</style>', re.DOTALL | re.IGNORECASE)

MOTS_FRANCAIS = (
    'Enregistrer', 'Rechercher', 'Valider', 'Annuler', 'Précédent', 'Suivant',
    'Se déconnecter', 'Déconnexion', 'Tableau de bord', 'Retour', 'Filtrer',
    'Aucun', 'Aucune', 'Inscription', 'Formations', 'Séances', 'Leçons',
    'Présence', 'Absents', 'Utilisateurs', 'Rôles', 'Profil', 'Visites',
    'Bourses', 'Candidature', 'Recettes', 'Dépenses', 'Solde', 'Clôture',
    'Motif', 'Montant', 'Libellé', 'Statut', 'Étudiant', 'Caisse',
    'Encaissable', 'Toutes', 'Tous', 'Voir', 'Ajouter', 'Modifier',
    'Supprimer', 'Choisir', 'Créer', 'Nouveau', 'Nouvelle',
)

# Contenu de base de données, volontairement en français : la plateforme ne
# traduit pas ce que les agents saisissent ou ce que les migrations sèment.
# Cette liste ne couvre que le jeu d'essai ; le reste est dérivé de la base.
DONNEES = (
    'Développement Web', 'Module HTML', 'Les bases du HTML', 'Cours de test',
    'Caisse principale', 'Lun-Ven 08h-10h', 'Nouveau Guichet',
)


class RenduAnglaisSansMelangeTest(BusinessTestBase):
    @property
    def users_by_role(self):
        return {
            'SUPER_ADMIN': self.super_admin,
            'ADMIN': self.admin,
            'DIRECTION': self.direction,
            'ASSISTANT_ADMIN': self.assistant,
            'SECRETAIRE': self.secretaire,
            'RESP_PEDA': self.peda,
            'FORMATEUR': self.formateur,
            'ETUDIANT': self.etudiant,
        }

    def client_en_anglais(self, user=None):
        """Client dont la session est verrouillée sur l'anglais."""
        client = Client()
        if user is not None:
            client.force_login(user)
        client.post(reverse('set_language'), {'language': 'en', 'next': '/'})
        return client

    def _donnees(self):
        """Toute chaîne stockée en base : rôles, catégories, motifs, intitulés."""
        chaines = set(DONNEES)
        sources = (
            (Role, 'label'),
            (TransactionCategory, 'name'),
            (VisitReason, 'label'),
            (CashAccount, 'name'),
            (Course, 'title'),
            (Course, 'domain'),
            (Course, 'description'),
            (CourseSession, 'schedule'),
            (Module, 'title'),
            (Lesson, 'title'),
        )
        for modele, champ in sources:
            chaines.update(
                valeur for valeur in
                modele.objects.values_list(champ, flat=True) if valeur)
        # Le nom et la signature de l'établissement sont des réglages de la
        # direction, pas de la chrome : ils déménagent, la garde doit suivre.
        reglages = PlatformSetting.objects.first()
        if reglages is not None:
            chaines.update(valeur for valeur in
                           (reglages.nom, reglages.signature, reglages.adresse)
                           if valeur)
        for user in User.objects.all():
            chaines.update(valeur for valeur in
                           (user.first_name, user.last_name) if valeur)
        return sorted(chaines, key=len, reverse=True)

    def _fuites(self, page, etiquette):
        texte = page.content.decode('utf-8')
        texte = COMMENTAIRE_RE.sub(' ', texte)
        texte = STYLE_RE.sub(' ', texte)
        for donnee in self._donnees():
            texte = texte.replace(donnee, '·')
        vues = []
        # Sensible à la casse : le « document » du JavaScript n'est pas de la chrome.
        for mot in MOTS_FRANCAIS:
            for match in list(re.finditer(r'\b' + re.escape(mot) + r'\b', texte))[:2]:
                debut = max(match.start() - 70, 0)
                vues.append(f'{mot} … {texte[debut:match.end() + 40]!r}')
        self.assertEqual(vues, [], f'chrome française visible sur {etiquette}')

    def test_chaque_tableau_de_bord_se_peint_en_anglais(self):
        self.assertEqual(
            set(self.users_by_role),
            {membre.value for membre in RoleKey} - set(ROLES_DISSOUS),
            'un poste actif sans compte de test, ou un poste dissous encore proposé',
        )
        for cle, user in self.users_by_role.items():
            page = self.client_en_anglais(user).get(
                reverse('core:dashboard:dashboard-router'), follow=True)
            self.assertEqual(page.status_code, 200, cle)
            self.assertContains(page, '<html lang="en"')
            self._fuites(page, f'tableau de bord {cle}')

    def test_pages_publiques_en_anglais(self):
        client = self.client_en_anglais()
        for route in ('core:login', 'core:home'):
            page = client.get(reverse(route), follow=True)
            self.assertEqual(page.status_code, 200, route)
            self._fuites(page, route)

    def test_listes_et_formulaires_se_peignent_en_anglais(self):
        ecriture = CashTransaction.objects.create(
            tx_type=CashTransaction.Type.IN, category=self.income_category,
            label='Recette de test', amount=5000, occurred_at=timezone.now(),
            account=self.cash, method=Payment.Method.CASH,
            status=CashTransaction.Status.VALIDATED, created_by=self.assistant,
        )
        pages = (
            (self.secretaire, 'core:dashboard:student-list'),
            (self.assistant, 'core:dashboard:journal'),
            (self.assistant, 'core:dashboard:transaction-detail', ecriture.pk),
            (self.assistant, 'core:dashboard:transaction-edit', ecriture.pk),
            (self.assistant, 'core:dashboard:accounts'),
            (self.assistant, 'core:dashboard:account-update', self.cash.pk),
            (self.assistant, 'core:dashboard:account-adjust', self.cash.pk),
            (self.assistant, 'core:dashboard:account-reset', self.cash.pk),
            (self.assistant, 'core:dashboard:categories'),
            (self.assistant, 'core:dashboard:category-update',
             self.income_category.pk),
            (self.assistant, 'core:dashboard:closures'),
            (self.assistant, 'core:dashboard:payment-create'),
            (self.assistant, 'core:dashboard:payment-months'),
            (self.peda, 'core:dashboard:programs'),
            (self.peda, 'core:dashboard:course-sessions'),
            (self.peda, 'core:dashboard:resp-peda-dashboard'),
            (self.formateur, 'core:dashboard:formateur-dashboard'),
            (self.etudiant, 'core:dashboard:etudiant-dashboard'),
            (self.peda, 'core:dashboard:resources'),
            (self.peda, 'core:dashboard:attendance-history'),
            (self.peda, 'core:dashboard:access-requests'),
            (self.assistant, 'core:dashboard:visit-list'),
            (self.assistant, 'core:dashboard:prospect-list'),
            (self.assistant, 'core:dashboard:visit-reasons'),
            (self.super_admin, 'core:dashboard:user-list'),
            (self.super_admin, 'core:dashboard:role-permissions'),
            (self.super_admin, 'core:dashboard:access-requests'),
            (self.super_admin, 'core:dashboard:audit-log'),
            (self.super_admin, 'core:dashboard:scholarship-review-list'),
            (self.super_admin, 'core:dashboard:finance-supervision'),
            (self.direction, 'core:dashboard:enrollment-detail', self.enrollment.pk),
            (self.secretaire, 'core:dashboard:student-detail', self.etudiant.pk),
            (self.etudiant, 'core:dashboard:student-course-sheet', self.session.pk),
        )
        for page_def in pages:
            user, route = page_def[0], page_def[1]
            url = reverse(route, args=page_def[2:])
            page = self.client_en_anglais(user).get(url, follow=True)
            self.assertEqual(page.status_code, 200, route)
            self._fuites(page, route)

    def test_le_calendrier_se_peint_en_anglais(self):
        annee = AcademicYear.objects.create(
            label='2026-2027', start_date=self.today - dt.timedelta(days=200),
            end_date=self.today + dt.timedelta(days=100), is_current=True)
        client = self.client_en_anglais(self.direction)
        liste = client.get(reverse('core:dashboard:academic-years'), follow=True)
        self.assertEqual(liste.status_code, 200)
        self._fuites(liste, 'années académiques')
        self.assertContains(liste, 'Academic years')
        reglage = client.get(
            reverse('core:dashboard:academic-year-update', args=[annee.pk]),
            follow=True)
        self.assertEqual(reglage.status_code, 200)
        self._fuites(reglage, "réglage d'une année")
        self.assertContains(reglage, 'Current year')
        etudiants = self.client_en_anglais(self.secretaire).get(
            reverse('core:dashboard:student-list'), follow=True)
        self._fuites(etudiants, 'sélecteur d année des étudiants')
        self.assertContains(etudiants, 'All years')
        self.assertContains(etudiants, 'Academic year 2026-2027')

    def test_les_parametres_generaux_se_peignent_en_anglais(self):
        client = self.client_en_anglais(self.direction)
        page = client.get(reverse('core:dashboard:platform-settings'),
                          follow=True)
        self.assertEqual(page.status_code, 200)
        self._fuites(page, 'paramètres généraux')
        self.assertContains(page, 'General settings')
        self.assertContains(page, 'Set up the institution')
        self.assertContains(page, 'What these settings cover')

    def test_la_grille_des_mois_et_le_recu_se_peignent_en_anglais(self):
        client = self.client_en_anglais(self.assistant)
        grille = client.get(reverse('core:dashboard:payment-months'),
                            {'enrollment': self.enrollment.pk}, follow=True)
        self.assertEqual(grille.status_code, 200)
        self._fuites(grille, 'grille des douze mois')
        self.assertContains(grille, 'Monthly payment of January')

        annee = timezone.localdate().year
        paiement = Payment.objects.create(
            enrollment=self.enrollment, amount=25000,
            method=Payment.Method.CASH, motif=Payment.Motif.MONTHLY,
            period_year=annee, period_month=1, recorded_by=self.assistant,
        )
        recu = client.get(reverse('core:dashboard:payment-receipt', args=[paiement.pk]))
        self.assertEqual(recu.status_code, 200)
        self._fuites(recu, 'reçu de paiement')
        self.assertContains(recu, 'Settled month')
        self.assertContains(recu, f'January {annee}')


class CompilationGabaritsTest(TestCase):
    """Les gabarits sont vérifiés avant de rendre : un écran muet ne se voit pas.

    Deux pièges mesurés ici. Une écriture de tag cassée lève une erreur à la
    compilation. Une variable à points dans un `{% blocktrans %}` ne lève rien :
    Django rend la place vide, et le titre de la fiche de cours perdait ainsi le
    nom de l'établissement sans jamais se plaindre.
    """

    def test_chaque_gabarit_du_projet_se_compile(self):
        racine = i18n_tools.BASE_DIR / 'templates'
        casses = []
        for chemin in i18n_tools.gabarits():
            relatif = chemin.relative_to(racine).as_posix()
            try:
                get_template(relatif)
            except Exception as erreur:
                casses.append(f'{relatif} : {type(erreur).__name__} — {erreur}')
        self.assertEqual(casses, [])

    def test_aucun_blocktrans_ne_garde_une_variable_a_points(self):
        suspects = []
        for chemin in i18n_tools.gabarits():
            msgids, _ = i18n_tools.extraire(chemin.read_text(encoding='utf-8'))
            suspects += [f'{chemin.name} : {m[:70]}' for m in msgids
                         if '{{' in m or '{%' in m]
        self.assertEqual(suspects, [])
