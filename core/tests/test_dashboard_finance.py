"""Période financière des tableaux de bord : mois courant par défaut."""
from datetime import datetime, timedelta

from django.urls import reverse
from django.utils import timezone

from core.models import CashTransaction

from .base import BusinessTestBase


class DashboardFinancePeriodeTest(BusinessTestBase):
    def setUp(self):
        self.cash.opening_balance = 1_000_000
        self.cash.save(update_fields=['opening_balance'])
        mois_courant = self.today.replace(day=10)
        mois_passe = (self.today.replace(day=1) - timedelta(days=1)).replace(day=10)

        self.entree_courante = self._operation(
            CashTransaction.Type.IN, 5000, mois_courant, self.income_category)
        self.sortie_courante = self._operation(
            CashTransaction.Type.OUT, 2000, mois_courant, self.expense_category)
        self.entree_passee = self._operation(
            CashTransaction.Type.IN, 9000, mois_passe, self.income_category)

    def _operation(self, tx_type, montant, jour, categorie):
        return CashTransaction.objects.create(
            tx_type=tx_type,
            label="Opération de test",
            amount=montant,
            account=self.cash,
            category=categorie,
            status=CashTransaction.Status.VALIDATED,
            occurred_at=timezone.make_aware(
                datetime(jour.year, jour.month, jour.day, 10, 0)),
            created_by=self.admin,
        )

    def test_le_tableau_admin_part_du_mois_en_cours(self):
        page = self.client_for(self.admin).get(
            reverse('core:dashboard:admin-dashboard'))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['finance_annee'], self.today.year)
        self.assertEqual(page.context['finance_mois'], self.today.month)
        self.assertEqual(page.context['finance_income'], 5000)
        self.assertEqual(page.context['finance_expense'], 2000)
        self.assertContains(page, 'Entrées du mois')
        self.assertContains(page, 'id_finance_mois')

    def test_le_filtre_annee_et_mois_change_les_totaux_admin(self):
        passe = self.entree_passee.occurred_at.date()
        page = self.client_for(self.admin).get(
            reverse('core:dashboard:admin-dashboard'),
            {'annee': passe.year, 'mois': passe.month})
        self.assertEqual(page.context['finance_income'], 9000)
        self.assertEqual(page.context['finance_expense'], 0)
        self.assertContains(page, f'value="{passe.month}" selected')

    def test_un_filtre_absurde_revient_au_mois_en_cours(self):
        page = self.client_for(self.admin).get(
            reverse('core:dashboard:admin-dashboard'),
            {'annee': 'pas-un-chiffre', 'mois': '99'})
        self.assertEqual(page.context['finance_annee'], self.today.year)
        self.assertEqual(page.context['finance_mois'], self.today.month)
        self.assertEqual(page.context['finance_income'], 5000)

    def test_le_tableau_super_admin_suit_aussi_le_filtre(self):
        client = self.client_for(self.super_admin)
        page = client.get(reverse('core:dashboard:super-admin-dashboard'))
        self.assertEqual(page.context['finance_income'], 5000)
        self.assertEqual(page.context['finance_expense'], 2000)
        self.assertEqual(page.context['finance_transaction_count'], 2)
        self.assertContains(page, 'Entrées du mois')
        self.assertContains(page, 'id_finance_mois')

        passe = self.entree_passee.occurred_at.date()
        page = client.get(reverse('core:dashboard:super-admin-dashboard'),
                          {'annee': passe.year, 'mois': passe.month})
        self.assertEqual(page.context['finance_income'], 9000)
        self.assertEqual(page.context['finance_expense'], 0)
        self.assertEqual(page.context['finance_transaction_count'], 1)
        self.assertContains(page, 'Sorties du mois')

    def test_le_tableau_assistant_a_le_meme_filtre(self):
        client = self.client_for(self.direction)
        page = client.get(reverse('core:dashboard:secretaire-dashboard'))
        self.assertEqual(page.context['finance_income'], 5000)
        self.assertEqual(page.context['finance_expense'], 2000)
        self.assertContains(page, 'Sorties du mois')

        passe = self.entree_passee.occurred_at.date()
        page = client.get(reverse('core:dashboard:secretaire-dashboard'),
                          {'annee': passe.year, 'mois': passe.month})
        self.assertEqual(page.context['finance_income'], 9000)
        self.assertContains(page, 'Solde du mois')

    def test_la_comptabilite_suit_le_meme_filtre(self):
        passe = self.entree_passee.occurred_at.date()
        page = self.client_for(self.direction).get(
            reverse('core:dashboard:comptabilite-dashboard'),
            {'annee': passe.year, 'mois': passe.month})
        self.assertEqual(page.context['total_revenue_month'], 9000)
        self.assertEqual(page.context['total_expenses_month'], 0)
        self.assertEqual(page.context['net_month'], 9000)
