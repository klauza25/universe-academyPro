"""Récupérer les classeurs Google en ligne, les analyser et les importer.

La commande fait le trajet complet, dans l'ordre où le métier le demande :

1. télécharger les feuilles configurées (export public ou compte de service) ;
2. classer chaque classeur reçu (journal de caisse / élèves / inconnu) ;
3. produire le rapport ``analyser_donnees`` dans le dossier du jour ;
4. sur ``--ecrire`` seulement, copier la base puis lancer les importeurs
   existants (formations, élèves, journal de caisse).

Sans ``--ecrire``, rien n'est écrit en base : c'est la répétition en ligne de
la prévisualisation que les importeurs font déjà sur des fichiers locaux.

Avec ``--ecrire``, la copie de sécurité est posée avant les importeurs. Si
aucun d'eux ne modifie réellement la base, la copie est retirée : la tâche
horaire ne remplit pas ``backups/`` de copies identiques.

    python manage.py synchroniser_classeurs                  # aperçu
    python manage.py synchroniser_classeurs --ecrire         # copie + imports
    python manage.py synchroniser_classeurs --feuille <id> --feuille <id>

Les identifiants viennent de ``--feuille``, sinon de ``CLASSEURS_GOOGLE_IDS``
(identifiants séparés par des virgules), sinon des deux feuilles du bureau.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import google_sheets
from core.sauvegarde import empreinte_base, sauvegarder_base


class Command(BaseCommand):
    help = ('Télécharge les classeurs Google, les analyse et, sur --ecrire, '
            'les importe dans la base après une copie de sécurité.')

    def add_arguments(self, parser):
        parser.add_argument('--feuille', action='append', default=None,
                            metavar='ID',
                            help='Identifiant Google Sheets (répétable)')
        parser.add_argument('--credentials', default=None,
                            help='JSON du compte de service (défaut : '
                                 '~/.config/academy/service-account.json)')
        parser.add_argument('--dossier', default=None,
                            help='Dossier de réception (défaut : '
                                 'docs/donnees/import_<date>)')
        parser.add_argument('--sans-telechargement', action='store_true',
                            help='Analyser les fichiers déjà présents dans le dossier')
        parser.add_argument('--sans-analyse', action='store_true',
                            help='Ne pas produire le rapport analyser_donnees')
        parser.add_argument('--importer', default='auto',
                            choices=('auto', 'etudiants', 'journal',
                                     'formations', 'aucun'),
                            help='Importeur à lancer sur --ecrire (défaut : auto)')
        parser.add_argument('--ecrire', action='store_true',
                            help='Copier la base puis écrire en base')
        parser.add_argument('--efface', action='store_true',
                            help='Passer --efface à importer_etudiants')
        parser.add_argument('--caisse', default=None,
                            help='Caisse des encaissements importés')
        parser.add_argument('--details', type=int, default=14,
                            help='Lignes détaillées dans les compte rendus')

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        dossier = Path(options['dossier'] or (
            Path(settings.BASE_DIR) / 'docs' / 'donnees'
            / f'import_{timezone.localdate():%Y-%m-%d}'))
        dossier.mkdir(parents=True, exist_ok=True)

        if not options['sans_telechargement']:
            self._archiver(dossier)
            self._telecharger(dossier, options)

        fichiers = sorted(dossier.glob('*.xlsx'))
        if not fichiers:
            raise CommandError(f'Aucun classeur .xlsx dans {dossier}.')

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\nClasseurs reçus dans {dossier}'))
        classement = {}
        for chemin in fichiers:
            categorie = google_sheets.classer_classeur(chemin)
            classement[chemin] = categorie
            self.stdout.write(
                f'  {chemin.name} — {categorie} '
                f'({len(google_sheets.onglets(chemin))} onglet(s))')

        if not options['sans_analyse']:
            self.stdout.write(self.style.MIGRATE_HEADING(
                '\nAnalyse en lecture seule'))
            call_command(
                'analyser_donnees', repertoire=str(dossier),
                sortie=str(dossier / 'RAPPORT_ANALYSE.md'),
                details=options['details'], stdout=self.stdout,
                stderr=self.stderr,
            )

        if not options['ecrire']:
            self.stdout.write(self.style.WARNING(
                '\nPrévisualisation : rien n’a été écrit. Relancez avec '
                '--ecrire pour copier la base et lancer les importeurs.'))
            return

        avant = empreinte_base()
        copie = sauvegarder_base()
        self.stdout.write(self.style.WARNING(
            f'Copie de sécurité posée avant écriture : {copie}' if copie
            else 'Pas de copie SQLite (base non SQLite) : sauvegardez par '
                 'l’outil d’exploitation avant d’écrire.'))

        self._importer(dossier, classement, options)

        # Une tâche horaire ne doit pas remplir backups/ de copies identiques.
        # Si les importeurs n'ont rien changé, la copie posée ne protège rien
        # de plus que la précédente : on la retire. Un import qui échoue lève
        # avant d'arriver ici, donc sa copie reste en place.
        if copie and avant is not None and empreinte_base() == avant:
            try:
                copie.unlink()
                self.stdout.write(
                    'Aucune écriture détectée : copie de sécurité retirée.')
            except OSError as erreur:
                self.stdout.write(self.style.WARNING(
                    f'Copie de sécurité conservée ({erreur}).'))
        elif copie:
            self.stdout.write(self.style.SUCCESS(
                f'Écriture effectuée : copie de sécurité conservée ({copie}).'))

    # ------------------------------------------------------------------
    @staticmethod
    def _archiver(dossier: Path) -> None:
        """Range les classeurs du passage précédent avant de retélécharger.

        Sans ce rangement, chaque passage de la tâche planifiée ajouterait une
        copie datée et les importeurs reliraient toutes les versions du jour :
        le rapport d'analyse compterait deux fois le même classeur. Les
        fichiers restent consultables sous ``archive/<horodatage>/``.
        """
        anciens = sorted(dossier.glob('*.xlsx'))
        rapport = dossier / 'RAPPORT_ANALYSE.md'
        if not anciens and not rapport.exists():
            return
        archive = dossier / 'archive' / datetime.now().strftime('%Y%m%d_%H%M%S')
        archive.mkdir(parents=True, exist_ok=True)
        for chemin in anciens:
            shutil.move(str(chemin), str(archive / chemin.name))
        if rapport.exists():
            shutil.move(str(rapport), str(archive / rapport.name))

    # ------------------------------------------------------------------
    def _telecharger(self, dossier: Path, options) -> None:
        identifiants = google_sheets.identifiants_feuilles(options['feuille'])

        for identifiant in identifiants:
            try:
                chemin = google_sheets.telecharger(
                    identifiant, dossier, options['credentials'])
            except google_sheets.AccesRefuse as refus:
                raise CommandError(
                    f'Feuille {identifiant} inaccessible.\n{refus}\n'
                    'Détail du partage : la feuille doit être publique en '
                    'lecture, ou partagée avec le client_email du compte de '
                    'service, et les API Drive/Sheets activées dans son projet.'
                ) from refus
            self.stdout.write(self.style.SUCCESS(
                f'  reçu {chemin.name} ({chemin.stat().st_size:,} octets)'
                .replace(',', ' ')))

    # ------------------------------------------------------------------
    def _importer(self, dossier: Path, classement: dict, options) -> None:
        choisi = options['importer']
        caisse = options['caisse']
        details = options['details']
        sortie = {'stdout': self.stdout, 'stderr': self.stderr}
        caisse_option = {'caisse': caisse} if caisse else {}

        if choisi in ('auto', 'formations'):
            self.stdout.write(self.style.MIGRATE_HEADING(
                '\nVague 1 — formations'))
            call_command('importer_formations', repertoire=str(dossier),
                         ecrire=True, **sortie)

        if choisi in ('auto', 'etudiants'):
            for chemin, categorie in classement.items():
                if categorie != 'etudiants':
                    continue
                self.stdout.write(self.style.MIGRATE_HEADING(
                    f'\nVague 2 — élèves ({chemin.name})'))
                call_command(
                    'importer_etudiants', repertoire=str(dossier),
                    classeur=chemin.name, ecrire=True,
                    efface=options['efface'], details=details,
                    **caisse_option, **sortie,
                )

        if choisi in ('auto', 'journal'):
            for chemin, categorie in classement.items():
                if categorie != 'journal':
                    continue
                self.stdout.write(self.style.MIGRATE_HEADING(
                    f'\nJournal de caisse ({chemin.name})'))
                call_command(
                    'importer_feuille', classeur=str(self._relatif(chemin)),
                    ecrire=True, details=details,
                    **caisse_option, **sortie,
                )

        if choisi == 'auto' and 'inconnu' in classement.values():
            self.stdout.write(self.style.WARNING(
                '\nCertains classeurs n’ont pas été reconnus : aucun importeur '
                'ne leur a été appliqué. Vérifiez le rapport d’analyse.'))

    @staticmethod
    def _relatif(chemin: Path) -> Path:
        """Le chemin tel que ``importer_feuille`` l'attend : depuis docs/donnees."""
        racine = Path(settings.BASE_DIR) / 'docs' / 'donnees'
        try:
            return chemin.relative_to(racine)
        except ValueError:
            return chemin
