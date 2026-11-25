"""Remise privée des identifiants étudiants depuis le back-office."""
from __future__ import annotations

import csv
from datetime import datetime

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from . import identifiants
from .decorators import user_management_required
from .models import RoleKey, User
from .utils import log_audit


def _etudiants():
    return User.objects.filter(roles__key=RoleKey.ETUDIANT).distinct()


@user_management_required
def page_identifiants(request):
    """Explique la remise avant toute écriture : les comptes vont être activés."""
    etudiants = _etudiants()
    return render(request, 'dashboard/super_admin/identifiants.html', {
        'total_etudiants': etudiants.count(),
        'sans_mot_de_passe': sum(
            1 for u in etudiants if not u.has_usable_password()),
        'en_attente_changement': etudiants.filter(
            password_must_change=True).count(),
        'domain': identifiants.DOMAINE,
    })


@user_management_required
@require_POST
def generer_identifiants(request):
    """Crée les identifiants manquants et rend le fichier privé à télécharger.

    Seuls les comptes sans mot de passe utilisable sont traités : relancer la
    page ne réinitialise pas un secret déjà remis à un étudiant.
    """
    candidats = [u for u in _etudiants() if not u.has_usable_password()]
    if not candidats:
        messages.info(request, _(
            "Aucun identifiant à générer : tous les étudiants ont déjà un mot de passe."))
        return redirect('core:dashboard:identifiants-page')

    lignes = identifiants.emettre(candidats)
    log_audit(request, 'CREDENTIALS_ISSUE', 'User', 'students',
              after={'count': len(lignes), 'domain': identifiants.DOMAINE})

    reponse = HttpResponse(content_type='text/csv; charset=utf-8')
    # i18n-exempt : nom de fichier technique, pas un texte affiché. i18n-exempt: filename
    reponse['Content-Disposition'] = (
        'attachment; filename="identifiants-etudiants-'  # i18n-exempt: filename
        f'{datetime.now():%Y-%m-%d}.csv"')
    reponse.write('\ufeff')
    ecrivain = csv.writer(reponse, delimiter=';')
    ecrivain.writerow([
        _('Email'), _('Mot de passe temporaire'), _('Code interne'),
        _('Prénom'), _('Nom'), _('Formation'),
    ])
    for ligne in lignes:
        ecrivain.writerow([
            ligne['email'], ligne['mot_de_passe'], ligne['code_interne'],
            ligne['prenom'], ligne['nom'], ligne['formation'],
        ])
    return reponse
