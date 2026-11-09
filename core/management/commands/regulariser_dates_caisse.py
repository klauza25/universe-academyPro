"""Ramener dans le présent les écritures de caisse datées dans l'avenir.

    python manage.py regulariser_dates_caisse            # aperçu, rien n'est écrit
    python manage.py regulariser_dates_caisse --ecrire    # corrige

L'import du journal de caisse a recopié les mois pré-remplis du classeur : la
date de l'écriture était celle du mois couvert, pas celle de l'encaissement.
Or une caisse ne se date pas dans l'avenir — le contrôle de cohérence
(`verifier_relations`) et l'audit financier le signalent tous les deux.

La correction ramène chaque ligne au jour où elle a été saisie et laisse
intact le mois réglé (``period_year`` / ``period_month``), seule description
de la période couverte. Le rapprochement étudiant ↔ mois payé n'est donc pas
perdu : seule la date de l'argent change.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core import i18n_tools
from core.models import AuditLog, CashTransaction, Payment


def _cible(instant, maintenant):
    """L'instant de saisie, jamais après maintenant."""
    if instant is None:
        return maintenant
    return instant if instant <= maintenant else maintenant


def _iso(instant):
    return timezone.localtime(instant).isoformat()


def dates_futures(*, ecrire: bool) -> dict:
    """Corrige (ou annonce) les paiements et écritures datés après maintenant.

    Rend un compte-rendu : lignes à corriger, montant concerné, mois réglés
    conservés. Sans ``ecrire``, rien n'est modifié en base.
    """
    maintenant = timezone.now()
    paiements = list(
        Payment.objects.filter(paid_at__gt=maintenant).order_by('paid_at')
    )
    ecritures = list(
        CashTransaction.objects.filter(occurred_at__gt=maintenant)
        .order_by('occurred_at')
    )
    rapport = {
        'paiements': paiements,
        'ecritures': ecritures,
        'corriges': 0,
        'montant': sum(p.amount for p in paiements),
    }

    if not ecrire or not (paiements or ecritures):
        return rapport

    with transaction.atomic():
        for paiement in paiements:
            avant = paiement.paid_at
            cible = _cible(paiement.created_at, maintenant)
            # Mise à jour par requête : la liste rendue au compte-rendu garde
            # l'ancienne date, donc l'aperçu --ecrire montre bien l'avant.
            Payment.objects.filter(pk=paiement.pk).update(paid_at=cible)
            if paiement.transaction_id:
                rapport['corriges'] += CashTransaction.objects.filter(
                    pk=paiement.transaction_id, occurred_at__gt=maintenant
                ).update(occurred_at=cible)
            AuditLog.objects.create(
                action='PAYMENT_DATE_FIX', entity_type='Payment',
                entity_id=str(paiement.pk),
                before_summary={'paid_at': _iso(avant)},
                after_summary={
                    'paid_at': _iso(cible),
                    'period_year': paiement.period_year,
                    'period_month': paiement.period_month,
                },
            )
            rapport['corriges'] += 1

        # Écritures de caisse sans paiement rattaché (sorties, autres recettes).
        restantes = list(
            CashTransaction.objects.filter(occurred_at__gt=maintenant)
        )
        for ecriture in restantes:
            avant = ecriture.occurred_at
            cible = _cible(ecriture.created_at, maintenant)
            CashTransaction.objects.filter(pk=ecriture.pk).update(
                occurred_at=cible)
            AuditLog.objects.create(
                action='CASH_DATE_FIX', entity_type='CashTransaction',
                entity_id=str(ecriture.pk),
                before_summary={'occurred_at': _iso(avant)},
                after_summary={'occurred_at': _iso(cible)},
            )
            rapport['corriges'] += 1

    return rapport


class Command(BaseCommand):
    help = ('Ramener au jour de saisie les paiements et écritures de caisse '
            'datés après aujourd’hui, sans toucher au mois réglé.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--ecrire', action='store_true',
            help='Corriger en base (sans cette option, simple aperçu).')

    def handle(self, *args, **options):
        i18n_tools.sortie_utf8()
        rapport = dates_futures(ecrire=options['ecrire'])
        paiements = rapport['paiements']
        ecritures = rapport['ecritures']

        if not paiements and not ecritures:
            self.stdout.write(self.style.SUCCESS(
                'Aucune écriture datée dans l’avenir : rien à corriger.'))
            return

        self.stdout.write(
            f'{len(paiements)} paiement(s) et {len(ecritures)} écriture(s) de '
            f'caisse datés après aujourd’hui '
            f'({timezone.localdate().strftime("%d/%m/%Y")}), '
            f'soit {rapport["montant"]:,} FCFA de recettes.'.replace(',', ' '))
        for paiement in paiements[:20]:
            self.stdout.write(
                f'  {paiement.reference}  {_iso(paiement.paid_at)[:16]} → '
                f'{_iso(_cible(paiement.created_at, timezone.now()))[:16]}'
                f'  (mois réglé : {paiement.period_month}/{paiement.period_year})')
        if len(paiements) > 20:
            self.stdout.write(f'  … et {len(paiements) - 20} autre(s) paiement(s).')
        for ecriture in ecritures[:20]:
            self.stdout.write(
                f'  {ecriture.reference}  {_iso(ecriture.occurred_at)[:16]} → '
                f'{_iso(_cible(ecriture.created_at, timezone.now()))[:16]}')
        if len(ecritures) > 20:
            self.stdout.write(f'  … et {len(ecritures) - 20} autre(s) écriture(s).')

        if not options['ecrire']:
            self.stdout.write(self.style.WARNING(
                'Prévisualisation : rien n’a été corrigé. Relancez avec '
                '--ecrire (après sauvegarde de db.sqlite3 dans backups/).'))
            return

        self.stdout.write(self.style.SUCCESS(
            f'{rapport["corriges"]} ligne(s) ramenée(s) au jour de saisie ; '
            'le mois réglé des paiements est conservé.'))
