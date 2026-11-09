"""Appliquer les migrations en attente, avec une copie de sécurité d'abord.

C'est la version appelable par un script de démarrage ou une tâche planifiée :
la commande pose elle-même la copie de ``db.sqlite3`` dans ``backups/`` avant
de toucher au schéma, puis applique ``migrate`` sans rien demander.

La copie n'est faite que s'il y a réellement une migration à appliquer. Une
tâche qui appelle ``migrer`` toutes les quinze minutes ne doit pas remplir
``backups/`` de copies identiques ; un schéma déjà à jour ne risque rien.

    python manage.py migrer                 # sauvegarde puis migrate
    python manage.py migrer --verifier      # + check et makemigrations --check
    python manage.py migrer --sans-sauvegarde

Une base PostgreSQL n'est pas copiée par la commande : sa sauvegarde relève de
``pg_dump``. Le ``migrate`` s'applique quand même.
"""
from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from core.sauvegarde import sauvegarder_base


def migrations_en_attente() -> list:
    """Le plan des migrations non appliquées sur la base par défaut.

    Une liste vide veut dire « schéma à jour ». Lève si l'état de la base ne
    peut pas être lu (base absente, verrou) : l'appelant décide alors de
    sauvegarder par précaution.
    """
    from django.db import connections
    from django.db.migrations.executor import MigrationExecutor

    executeur = MigrationExecutor(connections['default'])
    return executeur.migration_plan(executeur.loader.graph.leaf_nodes())


class Command(BaseCommand):
    help = ('Sauvegarde la base SQLite si des migrations attendent, puis les '
            'applique sans question (préalable aux imports et aux tâches '
            'planifiées).')

    def add_arguments(self, parser):
        parser.add_argument('--sans-sauvegarde', action='store_true',
                            help='Ne pas copier la base avant de migrer')
        parser.add_argument('--verifier', action='store_true',
                            help='Contrôler ensuite le projet et l’absence de '
                                 'migration manquante')

    def handle(self, *args, **options):
        if not options['sans_sauvegarde']:
            try:
                en_attente = migrations_en_attente()
            except Exception:
                # Base encore absente ou illisible : on sauvegarde par
                # précaution, quitte à ne rien avoir à restaurer.
                en_attente = None

            if en_attente == []:
                self.stdout.write(
                    'Aucune migration en attente : pas de copie inutile.')
            else:
                copie = sauvegarder_base()
                if copie:
                    self.stdout.write(self.style.WARNING(
                        f'Copie de sécurité : {copie}'))
                else:
                    self.stdout.write(
                        'Pas de copie SQLite (base non SQLite ou fichier '
                        'absent) : à sauvegarder par l’outil d’exploitation.')

        call_command('migrate', interactive=False, verbosity=1)
        self.stdout.write(self.style.SUCCESS('Migrations à jour.'))

        if options['verifier']:
            call_command('check')
            try:
                call_command('makemigrations', dry_run=True, check=True,
                             verbosity=1)
            except SystemExit as sortie:
                raise CommandError(
                    'Le code contient des changements de modèle sans migration : '
                    'lancez « manage.py makemigrations » avant de déployer.'
                ) from sortie
