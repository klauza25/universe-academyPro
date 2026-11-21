"""Compteurs de la page d'accueil de l'administration Django.

Les chiffres sont lus directement dans les modèles métier : l'admin technique ne
doit pas entretenir une seconde source de vérité. Une base indisponible (premier
lancement, migration en cours) donne des compteurs vides plutôt qu'une erreur 500.
"""
from django import template
from django.db import DatabaseError

from core.models import Course, Payment, RoleKey, User

register = template.Library()


@register.simple_tag
def ua_admin_stats():
    """Quatre compteurs lus en base, ou un dictionnaire vide si elle n'est pas prête."""
    try:
        return {
            'utilisateurs': User.objects.count(),
            'etudiants': User.objects.filter(roles__key=RoleKey.ETUDIANT).distinct().count(),
            'formations': Course.objects.count(),
            'paiements': Payment.objects.filter(status=Payment.Status.COMPLETED).count(),
        }
    except DatabaseError:
        return {}
