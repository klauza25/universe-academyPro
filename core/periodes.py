"""Borne de facturation retenue pour Universe Academy.

L'historique du classeur est importé : les mensualités déjà réglées avant
novembre 2026 restent visibles dans les dossiers. En revanche, aucun mois
antérieur à novembre 2026 ne devient une échéance à régler : la direction a
fixé le début de la facturation à ce mois-ci.

Ce module ne dépend que de ``datetime`` pour pouvoir être utilisé à la fois
par les modèles, les importeurs et les tests, sans risque d'import circulaire.
"""
from __future__ import annotations

import datetime as dt

DEBUT_FACTURATION = dt.date(2026, 11, 1)
"""Premier mois civil facturable, tel que demandé par la direction."""

__all__ = ['DEBUT_FACTURATION']
