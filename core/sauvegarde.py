"""Copies de sécurité de la base avant une écriture automatisée.

Les commandes manuelles demandent depuis toujours de copier ``db.sqlite3`` dans
``backups/`` avant d'écrire. Une tâche planifiée ne lit pas ce conseil : elle
appelle donc cette fonction, qui pose la copie elle-même et rend son chemin.

Une base PostgreSQL n'est pas copiée par ce module : la sauvegarde d'un serveur
relève de l'outil d'exploitation (``pg_dump``), pas d'un ``shutil.copy``.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from django.conf import settings


def sauvegarder_base(dossier: str | Path | None = None) -> Path | None:
    """Copie la base SQLite dans ``backups/`` et rend le fichier créé.

    Rend ``None`` quand la base n'est pas SQLite ou quand le fichier n'existe
    pas encore : il n'y a alors rien à copier.
    """
    base = settings.DATABASES['default']
    if 'sqlite3' not in base['ENGINE']:
        return None
    source = Path(base['NAME'])
    if not source.is_file():
        return None

    destination = Path(dossier or Path(settings.BASE_DIR) / 'backups')
    destination.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now().strftime('%Y%m%d_%H%M%S')
    cible = destination / f'db_{horodatage}_auto.sqlite3'
    numero = 2
    while cible.exists():
        cible = destination / f'db_{horodatage}_auto_{numero}.sqlite3'
        numero += 1

    shutil.copy2(source, cible)
    return cible


def empreinte_base() -> tuple[int, int] | None:
    """Signature légère de la base SQLite : date de modification et taille.

    Elle permet à un import de retirer la copie qu'il vient de poser quand
    aucune écriture n'a eu lieu : une tâche horaire ne doit pas empiler des
    copies identiques. Rend ``None`` pour une base non SQLite ou absente.
    """
    base = settings.DATABASES['default']
    if 'sqlite3' not in base['ENGINE']:
        return None
    source = Path(base['NAME'])
    if not source.is_file():
        return None
    etat = source.stat()
    return (etat.st_mtime_ns, etat.st_size)
