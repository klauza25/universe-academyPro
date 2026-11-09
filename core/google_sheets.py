"""Lecture en ligne des Google Sheets, en deux voies et sans jamais écrire.

Ordre des tentatives pour chaque feuille :

1. **Export public anonyme** — la feuille est partagée « Tout utilisateur
   disposant du lien ». Aucun identifiant n'est nécessaire et le fichier reçu
   est le vrai ``.xlsx`` de Google, types de cellules compris.
2. **Compte de service** — la feuille reste privée et a été partagée avec le
   ``client_email`` du compte. L'export Drive rend le même ``.xlsx`` ; si
   l'API Drive n'est pas activée, les valeurs sont relues par l'API Sheets et
   recopiées dans un classeur (les dates y arrivent alors en texte affiché).

Le module ne dépend pas de Django : ``docs/recuperer_classeurs_google.py``
l'utilise hors du projet, et les commandes de gestion s'en servent dans le
projet. Il ne fait que des GET.
"""
from __future__ import annotations

import os
import re
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import quote

EXPORT_PUBLIC = 'https://docs.google.com/spreadsheets/d/{id}/export?format=xlsx'
API_SHEETS = 'https://sheets.googleapis.com/v4/spreadsheets'
API_DRIVE_FILES = 'https://www.googleapis.com/drive/v3/files'
API_DRIVE_EXPORT = 'https://www.googleapis.com/drive/v3/files/{id}/export'
XLSX_MIME = ('application/vnd.openxmlformats-officedocument'
             '.spreadsheetml.sheet')
SCOPES = (
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/spreadsheets.readonly',
)
DEFAULT_CREDENTIALS = Path.home() / '.config' / 'academy' / 'service-account.json'
FEUILLES_PAR_DEFAUT = (
    '1skjUY883GPpTOlG9nYP_Z6PrAj60rQ47NvTfpRYygCU',
    '1GmjRV7T1dcLCD9kQd_hphdYLrO1Z6ezfgwd9xIA41gU',
)

MOTIF_JOURNAL = re.compile(r'enregistrement|op[ée]rations|feuille\s*2', re.I)
MOTIF_BASE_ETUDIANTS = re.compile(r'base\s*[ée]tudiants?', re.I)


class AccesRefuse(Exception):
    """La feuille n'est ni publique ni partagée avec le compte de service."""


# ----------------------------------------------------------------------
# Identifiants
# ----------------------------------------------------------------------
def chemin_identifiants(demande: str | os.PathLike | None = None) -> Path | None:
    """Le JSON du compte de service, ou ``None`` s'il n'y en a aucun.

    L'ordre est : argument explicite, ``GOOGLE_APPLICATION_CREDENTIALS``, puis
    ``~/.config/academy/service-account.json``. Un chemin annoncé mais absent
    lève ``AccesRefuse`` : mieux vaut le dire que retomber en silence sur
    l'export public.
    """
    candidat = demande or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    if not candidat:
        return DEFAULT_CREDENTIALS if DEFAULT_CREDENTIALS.is_file() else None

    chemin = Path(candidat).expanduser()
    if not chemin.is_file():
        raise AccesRefuse(
            f'Identifiants introuvables : {chemin}. Dépose le JSON du compte '
            'de service à cet endroit, ou passe --credentials.'
        )
    return chemin


def description_identifiants(demande: str | os.PathLike | None = None) -> dict:
    """Décrit le compte de service sans contacter Google.

    Sert au contrôle ``etat_google`` : on veut afficher le ``client_email``
    avant même de savoir si le réseau répond. Un JSON absent, illisible ou
    incomplet est rendu comme tel, jamais levé, pour que le rapport reste
    lisible.
    """
    import json

    try:
        chemin = chemin_identifiants(demande)
    except AccesRefuse as erreur:
        return {
            'chemin': str(demande
                          or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
                          or DEFAULT_CREDENTIALS),
            'existe': False,
            'valide': False,
            'erreur': str(erreur),
        }

    if chemin is None:
        return {
            'chemin': str(DEFAULT_CREDENTIALS),
            'existe': False,
            'valide': False,
        }

    try:
        donnees = json.loads(chemin.read_text(encoding='utf-8'))
    except (OSError, ValueError) as erreur:
        return {
            'chemin': str(chemin),
            'existe': True,
            'valide': False,
            'erreur': f'JSON illisible ({erreur})',
        }

    if not isinstance(donnees, dict):
        return {
            'chemin': str(chemin),
            'existe': True,
            'valide': False,
            'erreur': 'le JSON ne contient pas un objet',
        }

    return {
        'chemin': str(chemin),
        'existe': True,
        'valide': True,
        'type': donnees.get('type'),
        'client_email': donnees.get('client_email'),
        'client_id': donnees.get('client_id'),
        'project_id': donnees.get('project_id'),
    }


def identifiants_feuilles(demande: list[str] | None = None) -> list[str]:
    """Les identifiants à contrôler, dans l'ordre des priorités habituelles.

    ``--feuille`` d'abord, puis ``CLASSEURS_GOOGLE_IDS``, puis les deux
    classeurs du bureau. La même règle sert à la synchronisation et au
    contrôle d'accès, pour qu'ils ne divergent pas.
    """
    return list(demande or [
        identifiant.strip()
        for identifiant in os.getenv('CLASSEURS_GOOGLE_IDS', '').split(',')
        if identifiant.strip()
    ] or FEUILLES_PAR_DEFAUT)


# ----------------------------------------------------------------------
# Vérification d'accès (sans télécharger le classeur)
# ----------------------------------------------------------------------
def verifier_public(feuille_id: str) -> dict:
    """Teste l'export public en fermant le flux sans lire le contenu."""
    import requests

    try:
        reponse = requests.get(
            EXPORT_PUBLIC.format(id=feuille_id), timeout=30,
            allow_redirects=True, stream=True,
        )
    except requests.RequestException as erreur:
        return {'accessible': False,
                'detail': f'réseau indisponible ({erreur})'}

    try:
        type_recu = reponse.headers.get('Content-Type', '')
        if reponse.status_code in (401, 403, 404):
            return {'accessible': False, 'detail': f'HTTP {reponse.status_code}'}
        if not reponse.ok:
            return {'accessible': False, 'detail': f'HTTP {reponse.status_code}'}
        if 'spreadsheet' not in type_recu and 'octet-stream' not in type_recu:
            return {'accessible': False,
                    'detail': f'type inattendu ({type_recu or "inconnu"})'}
        return {'accessible': True, 'detail': f'HTTP {reponse.status_code}'}
    finally:
        reponse.close()


def verifier_compte_service(feuille_id: str,
                            credentials: str | Path) -> dict:
    """Interroge Drive et l'API Sheets sans lire le classeur.

    Les deux API sont testées séparément : un projet Cloud peut avoir activé
    Sheets sans Drive, et la synchronisation sait retomber sur la seconde.
    """
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    try:
        identifiants = service_account.Credentials.from_service_account_file(
            str(credentials), scopes=SCOPES,
        )
    except Exception as erreur:  # noqa: BLE001 — le rapport doit rester lisible
        detail = f'identifiants illisibles ({erreur})'
        return {
            'drive': {'accessible': False, 'detail': detail},
            'sheets': {'accessible': False, 'detail': detail},
            'titre': None,
        }

    session = AuthorizedSession(identifiants)
    resultat: dict = {'drive': None, 'sheets': None, 'titre': None}

    try:
        drive = session.get(
            f'{API_DRIVE_FILES}/{feuille_id}',
            params={'fields': 'id,name,mimeType',
                    'supportsAllDrives': 'true'},
            timeout=60,
        )
        if drive.ok:
            donnees = drive.json()
            resultat['drive'] = {
                'accessible': True,
                'detail': donnees.get('mimeType') or 'OK',
                'titre': donnees.get('name'),
            }
            resultat['titre'] = donnees.get('name')
        else:
            resultat['drive'] = {
                'accessible': False, 'detail': f'HTTP {drive.status_code}'}
    except Exception as erreur:  # noqa: BLE001
        resultat['drive'] = {
            'accessible': False, 'detail': f'réseau : {erreur}'}

    try:
        sheets = session.get(
            f'{API_SHEETS}/{feuille_id}',
            params={'fields': 'properties.title'}, timeout=60,
        )
        if sheets.ok:
            titre = sheets.json().get('properties', {}).get('title')
            resultat['sheets'] = {
                'accessible': True, 'detail': 'OK', 'titre': titre}
            resultat['titre'] = resultat['titre'] or titre
        else:
            resultat['sheets'] = {
                'accessible': False, 'detail': f'HTTP {sheets.status_code}'}
    except Exception as erreur:  # noqa: BLE001
        resultat['sheets'] = {
            'accessible': False, 'detail': f'réseau : {erreur}'}

    return resultat


# ----------------------------------------------------------------------
# Téléchargement
# ----------------------------------------------------------------------
def telecharger(feuille_id: str, dossier: str | Path,
                credentials: str | os.PathLike | None = None,
                titre: str | None = None) -> Path:
    """Télécharge une feuille dans ``dossier`` et rend le ``.xlsx`` écrit.

    ``titre`` sert de nom de fichier quand l'appelant le connaît déjà (API
    Sheets) ; sinon il est lu dans l'en-tête de l'export public.
    """
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)

    try:
        return _telecharger_public(feuille_id, dossier, titre)
    except AccesRefuse as publique:
        chemin = chemin_identifiants(credentials)
        if chemin is None:
            raise AccesRefuse(
                f'{publique}\nAucun compte de service trouvé. Deux issues : '
                'partager la feuille « Tout utilisateur disposant du lien » '
                '(Lecteur), ou déposer le JSON du compte de service dans '
                f'{DEFAULT_CREDENTIALS} et partager la feuille avec son '
                'client_email.'
            ) from publique
        return _telecharger_compte_service(feuille_id, dossier, chemin, titre)


def _telecharger_public(feuille_id: str, dossier: Path,
                        titre: str | None) -> Path:
    import requests

    reponse = requests.get(
        EXPORT_PUBLIC.format(id=feuille_id), timeout=60, allow_redirects=True,
    )
    if reponse.status_code in (401, 403, 404):
        raise AccesRefuse(
            f'La feuille {feuille_id} n’est pas publique '
            f'(HTTP {reponse.status_code}).'
        )
    reponse.raise_for_status()
    type_recu = reponse.headers.get('Content-Type', '')
    if 'spreadsheet' not in type_recu and 'octet-stream' not in type_recu:
        raise AccesRefuse(
            f'La feuille {feuille_id} n’a pas rendu un classeur '
            f'({type_recu or "type inconnu"}).'
        )

    nom = titre or _nom_depuis_entete(reponse.headers.get('Content-Disposition'))
    nom = nom or f'classeur_{feuille_id[:8]}'
    chemin = _chemin_libre(dossier, nom)
    chemin.write_bytes(reponse.content)
    return chemin


def _telecharger_compte_service(feuille_id: str, dossier: Path,
                                credentials: Path, titre: str | None) -> Path:
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    identifiants = service_account.Credentials.from_service_account_file(
        str(credentials), scopes=SCOPES,
    )
    session = AuthorizedSession(identifiants)
    titre = titre or _titre_google(session, feuille_id)

    # 1. L'export Drive rend le vrai classeur, types de cellules compris.
    reponse = session.get(
        API_DRIVE_EXPORT.format(id=feuille_id),
        params={'mimeType': XLSX_MIME}, timeout=120,
    )
    if reponse.ok and 'spreadsheet' in reponse.headers.get('Content-Type', ''):
        chemin = _chemin_libre(dossier, f'{titre}')
        chemin.write_bytes(reponse.content)
        return chemin

    # 2. L'API Sheets, seule activée dans certains projets, rend les valeurs.
    return _exporter_valeurs(session, feuille_id, dossier, titre, reponse)


def _titre_google(session, feuille_id: str) -> str:
    reponse = session.get(
        f'{API_SHEETS}/{feuille_id}',
        params={'fields': 'properties.title'}, timeout=60,
    )
    if reponse.ok:
        return reponse.json().get('properties', {}).get('title') \
            or f'classeur_{feuille_id[:8]}'
    return f'classeur_{feuille_id[:8]}'


def _exporter_valeurs(session, feuille_id: str, dossier: Path, titre: str,
                      echec_drive) -> Path:
    from openpyxl import Workbook

    meta = session.get(
        f'{API_SHEETS}/{feuille_id}',
        params={'fields': 'properties.title,sheets.properties.title'}, timeout=60,
    )
    if meta.status_code in (401, 403):
        raise AccesRefuse(
            'Le compte de service n’a pas accès à cette feuille, ou les API '
            'Google Sheets / Drive ne sont pas activées dans son projet '
            f'(HTTP {meta.status_code}). Détail Drive : '
            f'{echec_drive.text[:200]}'
        )
    meta.raise_for_status()
    onglets = [s['properties']['title']
               for s in meta.json().get('sheets', [])]

    classeur = Workbook()
    classeur.remove(classeur.active)
    utilises: set[str] = set()
    for onglet in onglets:
        valeurs = session.get(
            f'{API_SHEETS}/{feuille_id}/values/{quote(onglet, safe="")}',
            params={'valueRenderOption': 'FORMATTED_VALUE'}, timeout=60,
        ).json().get('values', [])
        feuille = classeur.create_sheet(_titre_excel(onglet, utilises))
        for ligne in valeurs:
            feuille.append([_cellule_texte(valeur) for valeur in ligne])

    chemin = _chemin_libre(dossier, titre)
    classeur.save(chemin)
    return chemin


# ----------------------------------------------------------------------
# Classement du classeur reçu
# ----------------------------------------------------------------------
def classer_classeur(chemin: str | Path) -> str:
    """Dit ce que le classeur contient : ``journal``, ``etudiants`` ou ``inconnu``.

    Les importeurs existants ne lisent pas au hasard : le journal de caisse
    n'est pas le classeur des élèves, et leur appliquer le mauvais serait pire
    que ne rien faire. Les motifs sont ceux de ``analyser_donnees``.
    """
    from openpyxl import load_workbook

    classeur = load_workbook(chemin, read_only=True, data_only=True)
    try:
        onglets = list(classeur.sheetnames)
    finally:
        classeur.close()

    # L'onglet « Base Etudiants » ne trompe pas : c'est la signature du
    # classeur des élèves. Les seuls noms de mois ne suffisent pas (le journal
    # de caisse en porte aussi), et « Données » apparaît dans plusieurs
    # classeurs : on reste donc sur des signatures franches.
    if any(MOTIF_BASE_ETUDIANTS.search(onglet) for onglet in onglets):
        return 'etudiants'
    if any(MOTIF_JOURNAL.search(onglet) for onglet in onglets):
        return 'journal'
    return 'inconnu'


def onglets(chemin: str | Path) -> list[str]:
    """Les noms d'onglets, pour le compte rendu de synchronisation."""
    from openpyxl import load_workbook

    classeur = load_workbook(chemin, read_only=True)
    try:
        return list(classeur.sheetnames)
    finally:
        classeur.close()


# ----------------------------------------------------------------------
# Outils de nommage
# ----------------------------------------------------------------------
def _nom_depuis_entete(entete: str | None) -> str | None:
    if not entete:
        return None
    etendue = re.search(r"filename\*=UTF-8''([^;]+)", entete, re.I)
    if etendue:
        from urllib.parse import unquote
        return unquote(etendue.group(1))
    simple = re.search(r'filename="?([^";]+)"?', entete, re.I)
    return simple.group(1) if simple else None


def _chemin_libre(dossier: Path, nom: str) -> Path:
    """Un nom de fichier sans caractères interdits, jamais écrasé.

    Le même classeur retéléchargé le même jour porte souvent le même titre :
    écraser l'ancien effacerait la trace de ce qui a été importé la fois
    précédente. On suffixe donc par la date, puis par un numéro.
    """
    base = _slug(Path(nom).stem)
    candidat = dossier / f'{base}.xlsx'
    if candidat.exists():
        candidat = dossier / f'{base}_{date.today():%Y%m%d}.xlsx'
    numero = 2
    while candidat.exists():
        candidat = dossier / f'{base}_{date.today():%Y%m%d}_{numero}.xlsx'
        numero += 1
    return candidat


def _slug(texte: str) -> str:
    texte = unicodedata.normalize('NFKD', texte).encode('ascii', 'ignore').decode()
    texte = re.sub(r'[^A-Za-z0-9]+', '_', texte).strip('_').lower()
    return texte or 'classeur'


def _titre_excel(nom: str, utilises: set[str]) -> str:
    """Un titre d'onglet Excel : 31 caractères, sans ``[]:*?/\\``, unique."""
    propre = re.sub(r'[\[\]:*?/\\]', '-', nom).strip() or 'Feuille'
    propre = propre[:31]
    titre, numero = propre, 2
    while titre in utilises:
        suffixe = f' ({numero})'
        titre = propre[: 31 - len(suffixe)] + suffixe
        numero += 1
    utilises.add(titre)
    return titre


def _cellule_texte(valeur):
    """Une valeur de l'API telle qu'Excel l'écrirait, sans formule exécutable."""
    if isinstance(valeur, str) and valeur.startswith('='):
        return "'" + valeur
    return valeur
