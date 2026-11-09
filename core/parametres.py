"""Les mots et les gardes de l'établissement, lus à un seul endroit.

Le nom, les coordonnées, le libellé de devise et le seuil d'alerte de caisse
étaient recopiés dans soixante gabarits et dans le code de caisse : la même
direction pouvait donc signer deux documents avec deux orthographes ou deux
numéros différents. Ce module est le seul lecteur de la table de réglages ; les
gabarits passent par le contexte `plateforme`, le code Python par les quatre
fonctions ci-dessous.

Lire n'écrit jamais : une page d'accueil ne peut pas créer la ligne de réglages
à la place de la direction. Tant qu'aucun écran n'a enregistré la sienne, les
valeurs par défaut du modèle servent de réponse — ce sont exactement celles
posées par la migration de départ.
"""

from .models import PlatformSetting


def ligne():
    """La ligne des réglages, ou une instance non sauvée portant les défauts."""
    return PlatformSetting.objects.first() or PlatformSetting()


def nom():
    return ligne().nom


def devise():
    return ligne().devise


def seuil_alerte():
    return ligne().seuil_alerte


def contacts():
    """Le bloc de coordonnées tel qu'il s'imprime : adresse, téléphone, e-mail."""
    return ligne().contacts()
