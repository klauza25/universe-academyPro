"""Compte rendu en lecture seule de la cohérence des relations entre tables.

    python manage.py verifier_relations              # tout contrôler
    python manage.py verifier_relations --maxi 0     # refuser un seul écart
    python manage.py verifier_relations --json       # pour un contrôle automatisé

La commande n'écrit rien : elle mesure. ``--maxi`` borne le nombre total
d'écarts tolérés ; au-delà, la commande échoue et le portique s'arrête là.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from core import relations


class Command(BaseCommand):
    help = ("Vérifie la cohérence des relations entre tables : paiements et "
            "écritures de caisse, nets des dossiers, soldes, journal d'audit.")

    def add_arguments(self, parser):
        parser.add_argument('--maxi', type=int, default=0,
                            help='Nombre maximum d\'écarts acceptés (0 par défaut).')
        parser.add_argument('--code', action='append', default=[],
                            help='Ne contrôler que ces codes (répétable).')
        parser.add_argument('--lignes', type=int, default=10,
                            help='Lignes détaillées par contrôle (10 par défaut).')
        parser.add_argument('--json', action='store_true', dest='en_json',
                            help='Rendre le compte rendu en JSON, sur une ligne.')

    def handle(self, *args, **options):
        constats = relations.controler(options['code'] or None)
        # Les signalements (journal d'audit) sont comptés à part : ils disent
        # une histoire de la base, ils ne la rendent pas fausse.
        total = sum(c.nombre for c in constats if not c.information)
        signalements = sum(c.nombre for c in constats if c.information)

        if options['en_json']:
            self.stdout.write(json.dumps(
                {
                    'total': total,
                    'signalements': signalements,
                    'maxi': options['maxi'],
                    'constats': [
                        {
                            'code': c.code,
                            'regle': c.regle,
                            'nombre': c.nombre,
                            'information': c.information,
                            'lignes': [{'entite': r, 'detail': d}
                                       for r, d in c.lignes[:options['lignes']]],
                        }
                        for c in constats
                    ],
                },
                ensure_ascii=False))
        else:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f'Cohérence des relations — {len(constats)} contrôles, '
                f'{total} écart(s), {signalements} signalement(s)'))
            for constat in constats:
                if not constat.nombre:
                    self.stdout.write(f'  [ok]   {constat.code}')
                    continue
                marque = 'signalement' if constat.information else 'écart'
                couleur = (self.style.WARNING if constat.information
                           else self.style.ERROR)
                self.stdout.write(couleur(
                    f'  [{marque}] {constat.code} — {constat.nombre} ligne(s) : '
                    f'{constat.regle}'))
                for ref, detail in constat.lignes[:options['lignes']]:
                    self.stdout.write(f'           {ref} · {detail}')
                if constat.nombre > options['lignes']:
                    self.stdout.write(
                        f'           … {constat.nombre - options["lignes"]} autre(s)')

        if total > options['maxi']:
            nommés = ', '.join(
                f'{c.code} ({c.nombre})'
                for c in constats if not c.information and c.nombre)
            raise CommandError(
                f'{total} écart(s) de cohérence, seuil accepté {options["maxi"]} : '
                f'{nommés}. Rien n\'a été modifié : voir `--lignes` pour le détail.')
        if options['en_json']:
            # Le compte rendu JSON est une ligne : une phrase de plus
            # rendrait le flux illisible pour qui le parse.
            return
        self.stdout.write(self.style.SUCCESS(
            f'Cohérence acceptée : {total} écart(s) pour un seuil de {options["maxi"]}.'))
