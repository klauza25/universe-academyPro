"""Télécharge des Google Sheets en classeurs .xlsx, en lecture seule.

Le travail réel vit dans ``core/google_sheets.py`` : export public anonyme
d'abord, puis compte de service (Drive ou API Sheets) si la feuille est privée.
Ce script n'est qu'une porte d'entrée hors Django, pour récupérer les fichiers
avant de les regarder.

Usage :
    .venv\\Scripts\\python.exe docs\\recuperer_classeurs_google.py <id> [<id> ...]

L'identifiant d'une feuille est la partie de l'URL comprise entre ``/d/`` et
``/edit`` :
    https://docs.google.com/spreadsheets/d/<id>/edit

Identifiants :
    ``--credentials`` ou ``GOOGLE_APPLICATION_CREDENTIALS``, sinon
    ``~/.config/academy/service-account.json``. Le compte de service doit avoir
    reçu l'accès « Lecteur » sur chaque feuille, et les API Google Drive/Sheets
    doivent être activées dans son projet Cloud.

Le script ne fait que des GET : il n'écrit jamais dans Google.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from core import google_sheets  # noqa: E402  (le chemin doit être posé avant)

DEFAUT_SORTIE = RACINE / 'docs' / 'donnees' / f'import_{date.today():%Y-%m-%d}'


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(
        description='Télécharge des Google Sheets en .xlsx (lecture seule).',
    )
    parseur.add_argument('feuilles', nargs='+', metavar='ID',
                         help='identifiant de la feuille dans son URL')
    parseur.add_argument('--credentials',
                         help='chemin du JSON du compte de service')
    parseur.add_argument('--out', default=str(DEFAUT_SORTIE),
                         help=f'dossier de sortie (défaut : {DEFAUT_SORTIE})')
    options = parseur.parse_args(argv)

    sortie = Path(options.out)
    for identifiant in options.feuilles:
        try:
            chemin = google_sheets.telecharger(
                identifiant, sortie, options.credentials)
        except google_sheets.AccesRefuse as refus:
            raise SystemExit(f'Feuille {identifiant} inaccessible :\n{refus}')
        categorie = google_sheets.classer_classeur(chemin)
        onglets = google_sheets.onglets(chemin)
        print(f'\n{chemin} ({chemin.stat().st_size:,} octets)'.replace(',', ' '))
        print(f'  classement : {categorie}')
        print(f'  onglets    : {len(onglets)} — {", ".join(onglets)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
