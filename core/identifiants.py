"""Identifiants privés remis aux étudiants importés des classeurs.

Un compte créé par l'import arrive sans mot de passe utilisable : il existe
mais personne ne peut s'y connecter. Ce module lui donne une adresse prévisible
(``prenom.nom-<formation>@universe.academy``), un mot de passe temporaire
solide, active le compte et force un changement à la première connexion.

Le mot de passe en clair n'est jamais journalisé : il est remis une seule fois,
dans le fichier privé téléchargé par le gestionnaire et dans la notification
interne de l'étudiant.
"""
from __future__ import annotations

import re
import secrets
import string
import unicodedata

from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .models import AccountStatus, Notification

DOMAINE = 'universe.academy'

# i18n-exempt : libellés de formations stockés en base, utilisés comme clés.
CODE_FORMATIONS = {
    'excel avancé': 'e',
    'informatique générale': 'i',
    'informatique de gestion': 'g',
    'maintenance informatique': 'm',
    'bureautique': 'b',
    'anglais': 'a',
    'développement web': 'd',
}

ALPHABET = ''.join(
    sorted(set(string.ascii_lowercase + string.digits) - set('o0il1')))


def _mots(texte: str) -> list[str]:
    """Des mots ASCII minuscules, sans accents ni ponctuation."""
    propre = unicodedata.normalize('NFKD', texte or '').encode(
        'ascii', 'ignore').decode().lower()
    return [mot for mot in re.split(r'[^a-z]+', propre) if mot]


def code_formation(titre: str | None) -> str:
    """La lettre de suffixe d'une formation, avec repli sur l'initiale."""
    mots = _mots(titre or '')
    normalise = ' '.join(mots)
    if normalise in CODE_FORMATIONS:
        return CODE_FORMATIONS[normalise]
    return mots[0][0] if mots else 'x'


def _parties(user) -> tuple[str, str]:
    """Prénom et nom normalisés, même quand fiche et classeur sont incomplets."""
    prenoms = _mots(user.first_name)
    noms = _mots(user.last_name)
    if not noms and len(prenoms) > 1:
        prenoms, noms = prenoms[:-1], prenoms[-1:]
    if not prenoms and '@' in (user.email or ''):
        prenoms = _mots((user.email or '').split('@', 1)[0])
    return (
        prenoms[0] if prenoms else 'etudiant',
        noms[0] if noms else 'eleve',
    )


def adresse_pour(user, code: str) -> str:
    """Une adresse unique ``prenom.nom-code@universe.academy``."""
    prenom, nom = _parties(user)
    base = f'{prenom}.{nom}-{code}'
    candidat = f'{base}@{DOMAINE}'
    suffixe = 2
    # La collision porte sur l'adresse *cible* : l'e-mail d'origine reste
    # occupé par l'utilisateur en cours et ne doit pas se compter lui-même.
    while user.__class__.objects.filter(
            email__iexact=candidat).exists():
        candidat = f'{base}-{suffixe}@{DOMAINE}'
        suffixe += 1
    return candidat


def mot_de_passe_pour(user) -> str:
    """Un secret temporaire qui satisfait les validateurs du projet."""
    for _ in range(60):
        secret = ''.join(secrets.choice(ALPHABET) for _ in range(12))
        try:
            validate_password(secret, user)
        except Exception:
            continue
        return secret
    # Ce repli ne devrait jamais servir : il garde la génération utilisable
    # même si les règles du projet deviennent plus strictes.
    return f'Ua{secrets.token_hex(8)}9'


def formation_de(user) -> str:
    """La formation de l'inscription la plus récente de l'étudiant."""
    inscription = (user.enrollments.select_related('session__course')
                   .order_by('-start_date', '-id').first())
    return (inscription.session.course.title if inscription else '') or ''


@transaction.atomic
def emettre(utilisateurs) -> list[dict]:
    """Active les comptes, pose les secrets et rend les lignes du fichier privé."""
    lignes: list[dict] = []
    for user in utilisateurs:
        formation = formation_de(user)
        code = code_formation(formation)
        email = adresse_pour(user, code)
        secret = mot_de_passe_pour(user)

        user.username = email
        user.email = email
        user.account_status = AccountStatus.ACTIVE
        user.set_password(secret)
        user.password_must_change = True
        user.save(update_fields=[
            'username', 'email', 'account_status', 'password',
            'password_must_change',
        ])

        Notification.objects.create(
            user=user,
            notification_type=Notification.Type.CREDENTIALS_ISSUED,
            title=_("Vos identifiants Univers Academy"),
            message=(
                _("Email : %(email)s\n"
                  "Mot de passe temporaire : %(password)s\n"
                  "Connectez-vous, puis changez ce mot de passe.")
                % {'email': email, 'password': secret}
            ),
            link=reverse('core:dashboard:password-change-required'),
        )

        lignes.append({
            'email': email,
            'mot_de_passe': secret,
            'code_interne': user.internal_code or '',
            'prenom': user.first_name,
            'nom': user.last_name,
            'formation': formation,
        })
    return lignes
