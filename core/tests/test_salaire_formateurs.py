"""Part de 30 % des paiements validés affichée par formateur.

Les montants sont des indicateurs de pilotage : aucun paiement, aucune écriture
de caisse et aucun modèle de paie n'est créé par ces écrans.
"""
import datetime as dt

from django.urls import reverse
from django.utils import timezone

from core.models import (
    CashTransaction, Payment, RoleKey, TransactionCategory,
)
from core.tests.base import BusinessTestBase
from core.utils import part_salaire_formateur, salaire_formateur, salaires_formateurs


class SalaireFormateurTests(BusinessTestBase):
    def paiement(self, montant, *, statut=Payment.Status.COMPLETED, cle='salaire-test'):
        return Payment.objects.create(
            enrollment=self.enrollment,
            amount=montant,
            currency='XAF',
            method=Payment.Method.CASH,
            status=statut,
            submission_key=cle,
            paid_at=timezone.now(),
        )

    def financer(self, montant=1000000):
        """Une recette précède les sorties : la garde de solde l'exige."""
        CashTransaction.objects.create(
            tx_type=CashTransaction.Type.IN, category=self.income_category,
            label='Financement du test', amount=montant, account=self.cash,
            status=CashTransaction.Status.VALIDATED, created_by=self.assistant,
        )

    def salaire_caisse(self, montant, *, categorie='Salaires', **champs):
        categorie_obj, ___ = TransactionCategory.objects.get_or_create(
            name=categorie, direction=TransactionCategory.Direction.OUT,
        )
        return CashTransaction.objects.create(
            tx_type=CashTransaction.Type.OUT, category=categorie_obj,
            label=champs.pop('label', 'Charges — Salaire du Personnel'),
            amount=montant, account=self.cash,
            status=champs.pop('status', CashTransaction.Status.VALIDATED),
            occurred_at=champs.pop('date', timezone.now()),
            created_by=self.assistant, **champs,
        )

    def test_part_30_pourcent_arrondie_a_l_unite(self):
        self.assertEqual(part_salaire_formateur(0), 0)
        self.assertEqual(part_salaire_formateur(100000), 30000)
        self.assertEqual(part_salaire_formateur(100001), 30000)
        self.assertEqual(part_salaire_formateur(100005), 30002)

    def test_seuls_les_paiements_valides_comptent(self):
        self.paiement(100000, cle='salaire-ok')
        self.paiement(50000, statut=Payment.Status.PENDING, cle='salaire-attente')
        self.paiement(50000, statut=Payment.Status.CANCELLED, cle='salaire-annule')
        self.paiement(50000, statut=Payment.Status.REFUNDED, cle='salaire-rembourse')

        resultat = salaire_formateur(self.formateur)
        self.assertEqual(resultat['payments_total'], 100000)
        self.assertEqual(resultat['salary'], 30000)

    def test_groupe_partage_par_deux_formateurs_compte_pour_chacun(self):
        confrere = self.make_user(RoleKey.FORMATEUR, 'confrere@test.local')
        self.session.formateurs.add(confrere)
        self.paiement(100000, cle='salaire-partage')

        lignes = {ligne['formateur'].id: ligne for ligne in salaires_formateurs()}
        for formateur in (self.formateur, confrere):
            with self.subTest(formateur=formateur.email):
                self.assertEqual(lignes[formateur.id]['sessions'], 1)
                self.assertEqual(lignes[formateur.id]['students'], 1)
                self.assertEqual(lignes[formateur.id]['payments_total'], 100000)
                self.assertEqual(lignes[formateur.id]['salary'], 30000)

    def test_formateur_sans_paiement_affiche_zero(self):
        sans_groupe = self.make_user(RoleKey.FORMATEUR, 'sans-groupe@test.local')
        lignes = {ligne['formateur'].id: ligne for ligne in salaires_formateurs()}
        self.assertEqual(lignes[sans_groupe.id]['payments_total'], 0)
        self.assertEqual(lignes[sans_groupe.id]['salary'], 0)
        self.assertEqual(lignes[sans_groupe.id]['sessions'], 0)

    def test_page_reservee_a_la_direction_et_a_la_comptabilite(self):
        url = reverse('core:dashboard:trainer-salaries')
        for user in (self.direction, self.assistant, self.admin, self.super_admin):
            with self.subTest(user=user.email):
                self.assertEqual(self.client_for(user).get(url).status_code, 200)
        for user in (self.formateur, self.etudiant, self.peda):
            with self.subTest(user=user.email):
                self.assertEqual(self.client_for(user).get(url).status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_page_affiche_chaque_formateur_et_sa_part(self):
        self.paiement(100000, cle='salaire-page')
        page = self.client_for(self.direction).get(
            reverse('core:dashboard:trainer-salaries'))

        self.assertContains(page, 'Salaires des formateurs')
        self.assertContains(page, self.formateur.email)
        self.assertContains(page, '100000')
        self.assertContains(page, '30000')
        self.assertContains(page, '30 %')

    def test_page_affiche_les_salaires_reellement_payes(self):
        self.financer()
        self.salaire_caisse(
            50000, counterparty='Hans',
            date=timezone.make_aware(dt.datetime(2026, 7, 17, 12)))
        self.salaire_caisse(30000, categorie='Avances sur salaire')
        self.salaire_caisse(20000, categorie='Paiements des formateurs')
        self.salaire_caisse(99999, status=CashTransaction.Status.DRAFT)
        CashTransaction.objects.create(
            tx_type=CashTransaction.Type.OUT, category=self.expense_category,
            label='Achat chargeur HP', amount=77777, account=self.cash,
            status=CashTransaction.Status.VALIDATED, created_by=self.assistant,
        )

        page = self.client_for(self.direction).get(
            reverse('core:dashboard:trainer-salaries'))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['total_salaires_payes'], 100000)
        self.assertEqual(page.context['nb_salaires_payes'], 3)
        self.assertContains(page, 'Salaires réellement payés')
        self.assertContains(page, 'Hans')
        self.assertNotContains(page, '99999')
        self.assertNotContains(page, '77777')

    def test_filtres_des_salaires_payes(self):
        self.financer()
        self.salaire_caisse(
            50000, counterparty='Hans', description='Salaire de Mr Hans',
            date=timezone.make_aware(dt.datetime(2026, 7, 17, 12)))
        self.salaire_caisse(
            20000, categorie='Avances sur salaire', counterparty='Bède',
            date=timezone.make_aware(dt.datetime(2026, 8, 5, 12)))
        url = reverse('core:dashboard:trainer-salaries')

        recherche = self.client_for(self.direction).get(url, {'q': 'Hans'})
        self.assertEqual(recherche.context['total_salaires_payes'], 50000)

        categorie = self.client_for(self.direction).get(
            url, {'categorie': 'Avances sur salaire'})
        self.assertEqual(categorie.context['total_salaires_payes'], 20000)

        periode = self.client_for(self.direction).get(
            url, {'from': '2026-08-01', 'to': '2026-08-31'})
        self.assertEqual(periode.context['total_salaires_payes'], 20000)

        invalide = self.client_for(self.direction).get(url, {'from': '2026-09-31'})
        self.assertEqual(invalide.status_code, 200)
        self.assertEqual(invalide.context['date_from'], '')
        self.assertEqual(invalide.context['total_salaires_payes'], 70000)

    def test_formateur_voit_sa_propre_part_sur_son_tableau_de_bord(self):
        self.paiement(100000, cle='salaire-dashboard')
        page = self.client_for(self.formateur).get(
            reverse('core:dashboard:formateur-dashboard'))

        self.assertContains(page, 'Votre part estimée')
        self.assertContains(page, '30000')
