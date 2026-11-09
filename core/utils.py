from django.db.models import IntegerField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from .models import AccountStatus, AuditLog, Enrollment, Payment, RoleKey, User

# Tout rôle autre qu'étudiant désigne un membre du staff. La liste est dérivée
# de l'énumération pour qu'un rôle ajouté plus tard soit compté sans retouche.
STAFF_ROLE_KEYS = tuple(
    key for key in RoleKey.values if key != RoleKey.ETUDIANT
)


def students_count(*, only_active: bool = False):
    """Le nombre de comptes portant le rôle étudiant.

    Un compte qui cumule étudiant et encadrement ne compte qu'une fois : la
    jointure sur les rôles multiplierait sinon les lignes. « only_active »
    restreint aux comptes approuvés, ce que les tableaux de bord appellent
    « étudiants actifs ».
    """
    comptes = User.objects.filter(roles__key=RoleKey.ETUDIANT)
    if only_active:
        comptes = comptes.filter(account_status=AccountStatus.ACTIVE)
    return comptes.distinct().count()


def platform_counts():
    """Les trois nombres affichés en tête des tableaux de bord.

    « Utilisateurs » compte tous les comptes, y compris ceux en attente
    d'approbation. « Étudiants » ne retient que les comptes portant le rôle
    étudiant. « Staff » retient tout compte portant au moins un autre rôle :
    un compte sans rôle n'est donc ni étudiant ni staff.
    """
    return {
        'total_users': User.objects.count(),
        'total_students': students_count(),
        'total_staff': User.objects.filter(
            roles__key__in=STAFF_ROLE_KEYS
        ).distinct().count(),
    }


def outstanding_receivables():
    """Somme des restes à payer, dossier par dossier.

    Un trop-perçu sur un dossier ne doit pas réduire la dette d'un autre :
    on additionne donc ``max(total dû - payé, 0)`` pour chaque inscription active.
    """
    paid = Payment.objects.filter(
        enrollment=OuterRef('pk'),
        status=Payment.Status.COMPLETED,
    ).values('enrollment').annotate(total=Sum('amount')).values('total')

    dossiers = Enrollment.objects.filter(
        status=Enrollment.Status.ACTIVE
    ).select_related(
        'session__course'
    ).annotate(
        paid_total=Coalesce(
            Subquery(paid, output_field=IntegerField()), Value(0)
        )
    )
    return sum(
        max(dossier.total_due - dossier.paid_total, 0)
        for dossier in dossiers
    )


def enrollments_waiting_validation(limit=10):
    """Inscriptions ouvertes au guichet, en attente d'une validation.

    La file est la même sur chaque tableau de bord habilité à valider :
    direction, caisse, supervision pédagogique, super administrateur.
    """
    return (
        Enrollment.objects.filter(status=Enrollment.Status.PENDING)
        .select_related('student', 'session__course')
        .order_by('enrolled_at')[:limit]
    )


def get_client_ip(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def log_audit(request, action, entity_type, entity_id,
              before=None, after=None):
    actor = request.user if request and hasattr(request, 'user') and request.user.is_authenticated else None
    ip = get_client_ip(request) if request else None
    AuditLog.objects.create(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before_summary=before,
        after_summary=after,
        ip_address=ip,
    )
