"""Réglages de l'établissement : les mots de la direction et son calendrier.

Deux écrans, une même idée : ce que la direction décide se pose en base et se
lit partout. Les paramètres généraux donnent le nom, les coordonnées, la devise
et le seuil d'alerte de caisse ; l'année cochée « en cours » décide ce que
montrent les listes d'étudiants, d'inscrits et de groupes. Ces écrans ne font
que poser des réglages : rien n'est supprimé, une année révolue reste en base et
cesse simplement d'être cochée. Tant qu'aucune année n'est écrite, les listes
affichent toutes les années — l'application n'invente aucun calendrier à la
place de la direction.
"""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from . import annee_academique
from .decorators import role_required
from .forms import AcademicYearForm, PlatformSettingForm
from .models import (
    AcademicYear, AuditLog, CourseSession, Enrollment, PlatformSetting,
)
from .utils import log_audit


def _etat_reglages(reglages):
    """Ce que l'audit retient des réglages : les mots posés, rien de secret."""
    return {
        'nom': reglages.nom,
        'signature': reglages.signature,
        'adresse': reglages.adresse,
        'telephone': reglages.telephone,
        'email': reglages.email,
        'identifiants_legaux': reglages.bloc_legal(),
        'devise': reglages.devise,
        'seuil_alerte': reglages.seuil_alerte,
    }


@role_required('DIRECTION')
def parametres_generaux(request):
    """Les mots de l'établissement, enregistrés en base au lieu du code.

    Le nom, les coordonnées, le libellé de devise et le seuil d'alerte de caisse
    se changent ici et paraissent partout : c'est le seul endroit qui écrit la
    ligne de réglages, Django Admin la consulte sans la toucher.
    """
    en_place = PlatformSetting.objects.first()
    # L'état d'avant se relève tout de suite : la validation du formulaire écrit
    # déjà les nouvelles valeurs sur l'instance, et l'audit perdrait sa base.
    avant = _etat_reglages(en_place) if en_place else {}
    form = PlatformSettingForm(request.POST or None,
                               instance=en_place or PlatformSetting(id=1))
    if request.method == 'POST' and form.is_valid():
        reglages = form.save()
        log_audit(request, 'PLATFORM_SETTINGS_EDIT', 'PlatformSetting',
                  str(reglages.id), before=avant,
                  after=_etat_reglages(reglages))
        messages.success(request, _("Réglages de l'établissement enregistrés."))
        return redirect('core:dashboard:platform-settings')
    return render(request, 'dashboard/reglages/platform_settings.html', {
        'form': form,
        'reglages': form.instance,
        'historique': AuditLog.objects.filter(
            entity_type='PlatformSetting',
        ).select_related('actor').order_by('-created_at')[:20],
    })


def _etat_annee(annee):
    """Ce que l'audit retient d'une année : libellé, fenêtre, état."""
    return {
        'libelle': annee.label,
        'debut': str(annee.start_date),
        'fin': str(annee.end_date),
        'en_cours': annee.is_current,
    }


def _lignes():
    """Les années posées, chacune avec ce que sa fenêtre couvre réellement."""
    return [{
        'annee': annee,
        'groupes': annee_academique.fil_groupes(
            CourseSession.objects.all(), annee).count(),
        'inscriptions': annee_academique.fil_inscriptions(
            Enrollment.objects.all(), annee).count(),
    } for annee in AcademicYear.objects.all()]


@role_required('DIRECTION')
def annee_academique_list(request):
    """Le calendrier : créer une année, en cocher une seule « en cours »."""
    form = AcademicYearForm()
    if request.method == 'POST':
        form = AcademicYearForm(request.POST)
        if form.is_valid():
            avant_courante = list(
                AcademicYear.objects.filter(is_current=True)
                .values_list('label', flat=True)
            )
            annee = form.save()
            apres = _etat_annee(annee)
            if apres['en_cours'] and avant_courante:
                # Le modèle a décoché la précédente : la trace s'en lit ici.
                apres['decochee'] = avant_courante[0]
            log_audit(request, 'ACADEMIC_YEAR_CREATE', 'AcademicYear',
                      str(annee.id), after=apres)
            messages.success(
                request,
                _("Année « %(label)s » créée ; elle est désormais l'année en cours.") % {'label': annee.label}
                if annee.is_current else
                _("Année « %(label)s » créée.") % {'label': annee.label},
            )
            return redirect('core:dashboard:academic-years')
    return render(request, 'dashboard/reglages/academic_years.html', {
        'form': form,
        'lignes': _lignes(),
        'en_cours': annee_academique.en_cours(),
    })


@role_required('DIRECTION')
def annee_academique_update(request, year_id):
    """Régler une année : les dates se corrigent, le passé des listes reste."""
    annee = get_object_or_404(AcademicYear, id=year_id)
    form = AcademicYearForm(instance=annee)
    if request.method == 'POST':
        form = AcademicYearForm(request.POST, instance=annee)
        if form.is_valid():
            # `instance` est touché dès la validation : l'état d'avant se relit en base.
            avant = _etat_annee(AcademicYear.objects.get(pk=annee.pk))
            avant_courante = [
                label for label in
                AcademicYear.objects.filter(is_current=True)
                .exclude(pk=annee.pk).values_list('label', flat=True)
            ]
            annee = form.save()
            apres = _etat_annee(annee)
            if apres['en_cours'] and avant_courante:
                apres['decochee'] = avant_courante[0]
            log_audit(request, 'ACADEMIC_YEAR_EDIT', 'AcademicYear',
                      str(annee.id), before=avant, after=apres)
            messages.success(
                request, _("Année « %(label)s » mise à jour.") % {'label': annee.label})
            return redirect('core:dashboard:academic-years')
    return render(request, 'dashboard/reglages/academic_year_form.html', {
        'annee': annee,
        'form': form,
        'groupes': annee_academique.fil_groupes(
            CourseSession.objects.all(), annee).count(),
        'inscriptions': annee_academique.fil_inscriptions(
            Enrollment.objects.all(), annee).count(),
        'historique': AuditLog.objects.filter(
            entity_type='AcademicYear', entity_id=str(annee.id),
        ).select_related('actor').order_by('-created_at')[:20],
    })
