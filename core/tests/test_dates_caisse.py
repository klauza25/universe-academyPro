"""Aucune écriture de caisse ne se date dans l'avenir.

L'import du journal de caisse a recopié les mois pré-remplis du classeur : six
mensualités portaient la date du mois couvert (décembre 2026 à avril 2027)
alors que l'argent était déjà en caisse. La correction ramène la ligne au jour
de sa saisie et conserve le mois réglé.
"""
import datetime as dt

from django.utils import timezone

from core.management.commands.regulariser_dates_caisse import dates_futures
from core.models import AuditLog, CashTransaction, Payment
from core.tests.base import BusinessTestBase


class DatesFuturesTests(BusinessTestBase):
    def _paiement_futur(self, jours=40, mois=2, **champs):
        paiement = Payment.objects.create(
            enrollment=self.enrollment,
            amount=30000,
            method=Payment.Method.CASH,
            status=Payment.Status.COMPLETED,
            paid_at=timezone.now() + dt.timedelta(days=jours),
            recorded_by=self.assistant,
            motif=Payment.Motif.MONTHLY,
            period_year=2027,
            period_month=mois,
            **champs,
        )
        ecriture = CashTransaction.objects.create(
            tx_type=CashTransaction.Type.IN,
            category=self.income_category,
            label='Mensualité de test',
            amount=paiement.amount,
            account=self.cash,
            status=CashTransaction.Status.VALIDATED,
            occurred_at=paiement.paid_at,
            created_by=self.assistant,
        )
        paiement.transaction = ecriture
        paiement.save(update_fields=['transaction'])
        return paiement

    def test_l_apercu_ne_modifie_rien(self):
        paiement = self._paiement_futur()
        avant = paiement.paid_at

        rapport = dates_futures(ecrire=False)

        self.assertEqual(len(rapport['paiements']), 1)
        self.assertEqual(len(rapport['ecritures']), 1)
        paiement.refresh_from_db()
        self.assertEqual(paiement.paid_at, avant)
        self.assertFalse(AuditLog.objects.filter(action='PAYMENT_DATE_FIX').exists())

    def test_la_correction_date_la_ligne_du_jour_de_saisie(self):
        paiement = self._paiement_futur()

        rapport = dates_futures(ecrire=True)

        self.assertEqual(rapport['corriges'], 2)
        paiement.refresh_from_db()
        paiement.transaction.refresh_from_db()
        self.assertEqual(paiement.paid_at.date(), timezone.localdate())
        self.assertEqual(paiement.transaction.occurred_at, paiement.paid_at)
        self.assertLessEqual(paiement.paid_at, timezone.now())

    def test_le_mois_regle_est_conserve(self):
        paiement = self._paiement_futur()

        dates_futures(ecrire=True)

        paiement.refresh_from_db()
        self.assertEqual((paiement.period_year, paiement.period_month), (2027, 2))
        self.assertEqual(paiement.motif, Payment.Motif.MONTHLY)
        self.assertEqual(paiement.amount, 30000)

    def test_la_correction_est_tracee_dans_l_audit(self):
        paiement = self._paiement_futur()

        dates_futures(ecrire=True)

        entree = AuditLog.objects.get(action='PAYMENT_DATE_FIX',
                                      entity_id=str(paiement.pk))
        self.assertIn('paid_at', entree.before_summary)
        self.assertEqual(entree.after_summary['period_month'], 2)

    def test_une_ecriture_sans_paiement_est_corrigee(self):
        ecriture = CashTransaction.objects.create(
            tx_type=CashTransaction.Type.OUT,
            category=self.expense_category,
            label='Charge pointée sur un mois à venir',
            amount=10000,
            account=self.cash,
            status=CashTransaction.Status.DRAFT,
            occurred_at=timezone.now() + dt.timedelta(days=90),
            created_by=self.assistant,
        )

        dates_futures(ecrire=True)

        ecriture.refresh_from_db()
        self.assertEqual(ecriture.occurred_at.date(), timezone.localdate())
        self.assertTrue(AuditLog.objects.filter(
            action='CASH_DATE_FIX', entity_id=str(ecriture.pk)).exists())

    def test_apres_correction_plus_aucune_date_future(self):
        self._paiement_futur()
        self._paiement_futur(jours=200, mois=6)

        dates_futures(ecrire=True)

        self.assertFalse(Payment.objects.filter(paid_at__gt=timezone.now()).exists())
        self.assertFalse(
            CashTransaction.objects.filter(occurred_at__gt=timezone.now()).exists())
        self.assertEqual(dates_futures(ecrire=True)['corriges'], 0,
                         'une seconde passe ne corrige plus rien')
