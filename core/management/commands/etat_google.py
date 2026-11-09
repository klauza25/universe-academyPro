"""Contrôler l'accès aux Google Sheets sans télécharger les classeurs.

C'est le diagnostic à lancer avant de croire que la synchronisation est
configurée : il affiche le ``client_email`` du compte de service et teste,
feuille par feuille, l'export public puis les API Drive et Sheets. Aucun
fichier n'est écrit et aucun classeur n'est lu.

    python manage.py etat_google
    python manage.py etat_google --feuille <id>
    python manage.py etat_google --credentials <chemin.json>

La commande sort en erreur (code 1) si une feuille reste inaccessible par les
deux voies. C'est volontaire : une tâche planifiée doit pouvoir s'arrêter là.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core import google_sheets


class Command(BaseCommand):
    help = ('Affiche le compte de service et vérifie, feuille par feuille, '
            'l’accès public et l’accès par compte de service. Ne télécharge '
            'aucun classeur.')

    def add_arguments(self, parser):
        parser.add_argument('--feuille', action='append', default=None,
                            metavar='ID',
                            help='Identifiant Google Sheets (répétable)')
        parser.add_argument('--credentials', default=None,
                            help='JSON du compte de service (défaut : '
                                 '~/.config/academy/service-account.json)')

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        identifiants = google_sheets.description_identifiants(
            options['credentials'])
        self._afficher_identifiants(identifiants)

        feuilles = google_sheets.identifiants_feuilles(options['feuille'])
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\nFeuilles ({len(feuilles)})'))

        accessibles = 0
        for feuille in feuilles:
            public = google_sheets.verifier_public(feuille)
            compte = None
            if identifiants.get('valide'):
                compte = google_sheets.verifier_compte_service(
                    feuille, identifiants['chemin'])

            par_compte = bool(compte and (
                compte['drive']['accessible']
                or compte['sheets']['accessible']))
            accessible = public['accessible'] or par_compte
            accessibles += 1 if accessible else 0
            self._afficher_feuille(feuille, public, compte, accessible)

        inaccessibles = len(feuilles) - accessibles
        if inaccessibles:
            self.stdout.flush()
            raise CommandError(
                f'{inaccessibles} feuille(s) sur {len(feuilles)} restent '
                'inaccessible(s). Corrigez le partage ou les identifiants, '
                'puis relancez « manage.py etat_google ».')

        self.stdout.write(self.style.SUCCESS(
            f'\nBilan : {accessibles} feuille(s) accessible(s) '
            f'sur {len(feuilles)}.'))

    # ------------------------------------------------------------------
    def _afficher_identifiants(self, infos: dict) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING('Identifiants'))
        self.stdout.write(f'  Fichier      : {infos["chemin"]}')

        if not infos.get('existe'):
            self.stdout.write(self.style.WARNING(
                '  État         : absent'))
            if infos.get('erreur'):
                self.stdout.write(f'  Détail       : {infos["erreur"]}')
            self.stdout.write(
                '  → Créez un compte de service Google et déposez sa clé '
                'JSON à ce chemin.')
            return

        if not infos.get('valide'):
            self.stdout.write(self.style.ERROR('  État         : illisible'))
            self.stdout.write(
                f'  Détail       : {infos.get("erreur", "JSON invalide")}')
            return

        self.stdout.write(self.style.SUCCESS('  État         : présent'))
        self.stdout.write(f'  Type         : {infos.get("type") or "inconnu"}')
        self.stdout.write(
            f'  client_email : {infos.get("client_email") or "absent du JSON"}')
        self.stdout.write(
            f'  project_id   : {infos.get("project_id") or "absent du JSON"}')

    # ------------------------------------------------------------------
    def _afficher_feuille(self, feuille: str, public: dict,
                          compte: dict | None, accessible: bool) -> None:
        self.stdout.write(f'\n  {feuille}')

        if public['accessible']:
            self.stdout.write(self.style.SUCCESS(
                f'    publique      : oui ({public["detail"]})'))
        else:
            self.stdout.write(
                f'    publique      : non ({public["detail"]})')

        if compte is None:
            self.stdout.write(
                '    compte service: non testé (identifiants absents ou '
                'illisibles)')
        else:
            self._afficher_volet('Drive', compte['drive'])
            self._afficher_volet('Sheets API', compte['sheets'])

        if accessible:
            titre = (compte or {}).get('titre')
            suffixe = f' — « {titre} »' if titre else ''
            self.stdout.write(self.style.SUCCESS(
                f'    bilan         : accessible{suffixe}'))
        else:
            self.stdout.write(self.style.ERROR(
                '    bilan         : inaccessible'))

    def _afficher_volet(self, nom: str, volet: dict) -> None:
        if volet['accessible']:
            self.stdout.write(self.style.SUCCESS(
                f'    {nom:<13} : oui ({volet["detail"]})'))
        else:
            self.stdout.write(
                f'    {nom:<13} : non ({volet["detail"]})')
