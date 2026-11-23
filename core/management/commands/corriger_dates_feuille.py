"""Rattraper les écritures du journal dont la date fut perdue par le classeur.

Le journal laisse parfois la colonne « Date » vide : la ligne prolonge alors
celle du dessus. Les premières versions de `lire` dataient ces lignes du jour
de l'import, ce qui les faisait disparaître des filtres de date. La lecture est
désormais corrigée ; cette commande aligne les écritures déjà posées.

Sans ``--ecrire``, elle ne fait que montrer les écarts. Avec ``--ecrire``, elle
ne touche que les Mouvements de caisse marqués « d'après le journal de caisse »
dont le numéro de ligne existe dans le classeur et dont la date diffère.

    python manage.py corriger_dates_feuille                 # aperçu
    python manage.py corriger_dates_feuille --ecrire        # correction
"""
from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core import feuille_import, google_sheets
from core.models import CashTransaction

FEUILLE_JOURNAL = '1GmjRV7T1dcLCD9kQd_hphdYLrO1Z6ezfgwd9xIA41gU'


class Command(BaseCommand):
    help = 'Restaure la date du journal sur les écritures importées sans date.'

    def add_arguments(self, parser):
        parser.add_argument('--feuille', default=FEUILLE_JOURNAL,
                            help='Identifiant Google Sheets du journal')
        parser.add_argument('--classeur', default=None,
                            help='Fichier déjà reçu, dans docs/donnees')
        parser.add_argument('--details', type=int, default=40,
                            help='Nombre de corrections détaillées')
        parser.add_argument('--ecrire', action='store_true',
                            help='Appliquer les corrections en base')

    def handle(self, *args, **options):
        chemin = self._chemin(options)
        lignes = feuille_import.lire(chemin)
        par_ligne = {ligne.rang: ligne for ligne in lignes}

        corrections = []
        for tx in CashTransaction.objects.filter(
                note__startswith=feuille_import.MARQUE_FEUILLE):
            trouvée = re.search(r'ligne (\d+)', tx.note or '')
            if not trouvée:
                continue
            ligne = par_ligne.get(int(trouvée.group(1)))
            if ligne is None or ligne.date is None:
                continue
            if tx.occurred_at.date() == ligne.date.date():
                continue
            corrections.append((tx, ligne))

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\n{len(lignes)} ligne(s) lue(s) dans {chemin.name}.'))
        avec_paiement = sum(1 for tx, ___ in corrections
                            if getattr(tx, 'student_payment', None) is not None)
        self.stdout.write(f'{len(corrections)} écriture(s) à redater, '
                          f'dont {avec_paiement} paiement(s) étudiant(s) lié(s).')
        for tx, ligne in sorted(corrections,
                                key=lambda paire: paire[1].rang)[:options['details']]:
            self.stdout.write(
                f'  ligne {ligne.rang} — {tx.occurred_at.date()} → {ligne.date.date()}'
                f'  {tx.label[:48]}  {tx.amount:,} FCFA'.replace(',', ' '))

        if not options['ecrire']:
            self.stdout.write(self.style.WARNING(
                'Aperçu : rien n’a été écrit. Sauvegardez db.sqlite3, puis '
                'relancez avec --ecrire.'))
            return

        with transaction.atomic():
            for tx, ligne in corrections:
                instant = feuille_import.instant_de(ligne)
                tx.occurred_at = instant
                tx.save(update_fields=['occurred_at'])
                paye = getattr(tx, 'student_payment', None)
                if paye is not None and paye.paid_at.date() != instant.date():
                    paye.paid_at = instant
                    paye.save(update_fields=['paid_at'])
        self.stdout.write(self.style.SUCCESS(
            f'{len(corrections)} écriture(s) redatée(s).'))

    @staticmethod
    def _chemin(options) -> Path:
        if options['classeur']:
            chemin = Path('docs/donnees') / options['classeur']
            if not chemin.exists():
                raise CommandError(f'classeur introuvable : {chemin}')
            return chemin
        dossier = Path(settings.BASE_DIR) / 'docs' / 'donnees' / 'journal_dates'
        dossier.mkdir(parents=True, exist_ok=True)
        return google_sheets.telecharger(options['feuille'], dossier)
