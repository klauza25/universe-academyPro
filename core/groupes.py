"""La règle d'affectation des groupes, écrite une seule fois.

Un étudiant reçoit le contenu du groupe où son inscription le place : sans
formateur, le groupe existe mais personne ne peut y poser une séance ni une
ressource, et l'espace de l'étudiant reste vide. La règle vit ici parce que le
formulaire du tableau de bord et Django Admin doivent appliquer le même refus ;
la répéter dans une vue aurait rouvert la porte au trou.

Les groupes terminés ou annulés y échappent : ce sont des archives, souvent
reprises des classeurs, et exiger un formateur ferait échouer une simple
correction de date. Les écritures par lot (imports) passent par l'ORM, hors de
ce contrôle : c'est `verifier_relations` qui les signale.
"""
from django.utils.translation import gettext_lazy as _

from .models import CourseSession

# Statuts pour lesquels un formateur est exigé : le groupe va enseigner.
STATUTS_EXIGEANTS = (CourseSession.Status.PLANNED, CourseSession.Status.ACTIVE)


def formateur_requis(statut):
    """Si un groupe portant ce statut doit être affecté à un formateur."""
    return statut in STATUTS_EXIGEANTS


def erreur_affectation(statut, formateurs):
    """Le message de refus, ou rien quand l'affectation est conforme."""
    if formateur_requis(statut) and not formateurs:
        return _("Affectez au moins un formateur à ce groupe : sans lui, aucune séance ni ressource ne peut être publiée pour les inscrits.")
    return None


def applique_la_regle(formulaire):
    """Applique la règle aux données déjà nettoyées d'un formulaire de groupe."""
    erreur = erreur_affectation(
        formulaire.cleaned_data.get('status') or '',
        formulaire.cleaned_data.get('formateurs'),
    )
    if erreur:
        formulaire.add_error('formateurs', erreur)


def sans_formateur():
    """Les groupes en préparation ou en cours qui n'ont aucun formateur."""
    return (CourseSession.objects
            .filter(status__in=STATUTS_EXIGEANTS, formateurs__isnull=True)
            .select_related('course')
            .distinct()
            .order_by('starts_at'))
