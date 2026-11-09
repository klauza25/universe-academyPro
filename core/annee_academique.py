"""L'année académique en cours : un seul endroit sait ce qu'elle couvre.

La direction pose les dates et coche une année sur l'écran d'administration ;
ici vivent les règles qui en découlent : quelle année s'applique quand l'écran
ne dit rien, comment une valeur d'URL est lue, et ce que « faire partie de cette
année » veut dire pour un étudiant, une inscription ou un groupe.

L'ancrage est la date de début du groupe : c'est la seule donnée d'année déjà
présente partout. Un élève est donc de l'année où son groupe a commencé, et un
compte sans inscription n'appartient à aucune année — il ne se montre que sous
« Toutes les années ».

Tant qu'aucune année n'est posée, `en_cours()` rend `None` et les filtres
laissent les requêtes intactes : rien n'est inventé, les listes montrent tout.
"""
import uuid

from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from .models import AcademicYear, Enrollment

# Valeur du paramètre d'URL « annee_academique » qui réclame toutes les années.
TOUTES = 'all'  # i18n-exempt: valeur de paramètre d'URL, jamais affichée

# Un dossier annulé ne place personne dans une année : la formation n'a pas eu lieu.
STATUTS_SUIVIS = tuple(
    statut for statut in Enrollment.Status.values
    if statut != Enrollment.Status.CANCELLED
)


def en_cours():
    """L'année cochée par la direction, ou None si elle n'en a posé aucune."""
    return AcademicYear.objects.filter(is_current=True).first()


def toutes_les_annees():
    """Les années posées, dans l'ordre où les montrer au sélecteur."""
    return list(AcademicYear.objects.all())


def resoudre(valeur_get):
    """L'année à appliquer à l'écran, à partir du paramètre d'URL.

    « toutes » ne filtre rien ; une valeur reconnue filtre cette année ; une
    valeur absente ou périmée retombe sur l'année en cours — donc sur rien du
    tout si la direction n'a encore posé aucune année.
    """
    if valeur_get == TOUTES:
        return None
    if valeur_get and _est_un_identifiant(valeur_get):
        annee = AcademicYear.objects.filter(pk=valeur_get).first()
        if annee is not None:
            return annee
    return en_cours()


def depuis_la_requete(request):
    """L'année choisie sur l'écran, qu'elle arrive par l'URL ou par le formulaire.

    Les écrans d'encaissement renvoient le filtre dans une case cachée : sans
    cette lecture, un refus de saisie ferait revenir toute la liste des dossiers
    et ferait croire au guichet que l'année a changé sous ses pieds.
    """
    return resoudre(
        request.GET.get('annee_academique')  # i18n-exempt: nom du paramètre d'URL
        or request.POST.get('annee_academique')  # i18n-exempt: nom du paramètre d'URL
        or '')


def _est_un_identifiant(valeur):
    try:
        uuid.UUID(str(valeur))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def fil_groupes(queryset, annee):
    """Des groupes de formation, réduits à ceux démarrés dans l'année."""
    if annee is None:
        return queryset
    return queryset.filter(
        starts_at__gte=annee.start_date, starts_at__lte=annee.end_date)


def fil_inscriptions(queryset, annee):
    """Des dossiers d'inscription, réduits à l'année du groupe concerné."""
    if annee is None:
        return queryset
    return queryset.filter(
        Q(session__starts_at__gte=annee.start_date,
          session__starts_at__lte=annee.end_date),
        status__in=STATUTS_SUIVIS,
    )


def fil_etudiants(queryset, annee, extra=None):
    """Des comptes d'étudiants, réduits à ceux inscrits dans l'année.

    Tout tient dans un seul `filter()` : c'est le même dossier d'inscription qui
    doit être de l'année choisie et porter la formation filtrée. Deux `filter()`
    séparés laisseraient un étudiant de 2025 passer sous « 2026-2027 +
    Développement Web » pour une inscription ancienne. Le `distinct()` empêche
    un double inscrit d'apparaître deux fois.
    """
    condition = Q()
    if annee is not None:
        condition &= Q(
            enrollments__session__starts_at__gte=annee.start_date,
            enrollments__session__starts_at__lte=annee.end_date,
            enrollments__status__in=STATUTS_SUIVIS,
        )
    if extra is not None:
        condition &= extra
    return queryset.filter(condition).distinct()


def drapeau(annee):
    """Le mot à afficher quand un filtre est à l'œuvre, pour les bandeaux."""
    if annee is None:
        return _("Aucune année académique définie : toutes les années s'affichent.")
    return _("Année académique %(label)s (%(dates)s).") % {
        'label': annee.label,
        'dates': f'{annee.start_date} → {annee.end_date}',
    }
