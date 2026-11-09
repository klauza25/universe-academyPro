"""Cohérence des relations entre tables, vérifiée sans rien écrire.

Une écriture peut passer par un écran, par l'administration Django, par un
import ou par un script : ce module ne juge pas la porte d'entrée, il juge ce
qui est sorti en base. Chaque contrôle pose une relation que les modèles
promettent — un paiement effectué a son écriture de caisse, un dossier a un net
égal au tarif moins la remise, une écriture validée ne descend pas sous le
plancher d'une caisse — et rend les lignes qui y manquent.

Le module est strictement en lecture : il ne corrige, ne complète et ne
supprime rien. La commande ``verifier_relations`` le présente à l'écran de
console et le journal de test s'en sert de portique.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from . import groupes
from .models import (
    AccountStatus, Attendance, AuditLog, CashAccount, CashTransaction, Course,
    CourseSession, Enrollment, Payment, RoleKey, User,
)

MODELES = {m.__name__: m for m in apps.get_app_config('core').get_models()}

# La catégorie sous laquelle les écrans et les imports consignent une recette
# d'étudiant : seule celle-là promet un paiement au dossier.
CATEGORIE_RECETTE_ETUDIANTE = 'Paiements des étudiants'  # i18n-exempt: nom stocké en base, clé de get_or_create


@dataclass
class Constat:
    """Un contrôle et les lignes qui le violent, toutes écrites ensemble."""

    code: str
    regle: str
    lignes: list = field(default_factory=list)
    information: bool = False

    @property
    def nombre(self) -> int:
        return len(self.lignes)


def _date(valeur):
    return valeur.strftime('%d/%m/%Y') if valeur else '—'


def paiements_sans_ecriture():
    """Un paiement effectué doit avoir son écriture dans une caisse."""
    return [
        (p.reference, f'{p.amount} · {_date(p.paid_at)} · {p.enrollment.student.display_label}')
        for p in Payment.objects.filter(
            status=Payment.Status.COMPLETED, transaction__isnull=True
        ).select_related('enrollment__student').order_by('paid_at')
    ]


def ecritures_recette_sans_paiement():
    """Une recette d'étudiant encaissée doit se retrouver dans son dossier."""
    return [
        (t.reference, f'{t.amount} · {_date(t.occurred_at)} · {t.account.name} · {t.label}')
        for t in CashTransaction.objects.filter(
            tx_type=CashTransaction.Type.IN,
            status=CashTransaction.Status.VALIDATED,
            nature=CashTransaction.Nature.NORMAL,
            category__name=CATEGORIE_RECETTE_ETUDIANTE,
            student_payment__isnull=True,
        ).select_related('account').order_by('occurred_at')
    ]


def paiements_en_attente_ecritures_validees():
    """Deux écritures du même argent : le paiement dort et la caisse est déjà garnie."""
    return [
        (t.reference, f'{t.amount} · {_date(t.occurred_at)} · {t.label}')
        for t in CashTransaction.objects.filter(
            student_payment__status=Payment.Status.PENDING,
            status=CashTransaction.Status.VALIDATED,
        ).select_related('student_payment').order_by('occurred_at')
    ]


def transferts_incomplets():
    """Un transfert retire d'une caisse : il lui faut une autre destination."""
    return [
        (t.reference, f'{t.amount} · {_date(t.occurred_at)} · '
                      + ('destination absente' if t.destination_account_id is None
                         else 'aller et retour sur la même caisse'))
        for t in CashTransaction.objects.filter(
            tx_type=CashTransaction.Type.TRANSFER,
            status=CashTransaction.Status.VALIDATED,
        ).filter(Q(destination_account__isnull=True)
                 | Q(destination_account_id=F('account_id'))).order_by('occurred_at')
    ]


def ecritures_sans_compte():
    """Une écriture de caisse est toujours rattachée à une caisse."""
    return [
        (t.reference, f'{t.amount} · {_date(t.occurred_at)} · {t.label}')
        for t in CashTransaction.objects.filter(
            account__isnull=True).order_by('reference')
    ]


def nets_incoherents():
    """Le net dû d'un dossier vaut le tarif moins la remise, pas autre chose."""
    return [
        (f'{e.student.display_label} — {e.session.course.title}',
         f'tarif {e.tariff_amount} − remise {e.discount_amount} ≠ net {e.net_amount}')
        for e in Enrollment.objects.select_related(
            'student', 'session__course'
        ).exclude(
            net_amount=F('tariff_amount') - F('discount_amount')
        ).order_by('student__last_name')
    ]


def remises_superieures_au_tarif():
    """Une remise ne peut pas dépasser le tarif qu'elle réduit."""
    return [
        (f'{e.student.display_label} — {e.session.course.title}',
         f'remise {e.discount_amount} > tarif {e.tariff_amount}')
        for e in Enrollment.objects.select_related(
            'student', 'session__course'
        ).filter(discount_amount__gt=F('tariff_amount')).order_by('student__last_name')
    ]


def trop_perçus():
    """Ce qui est réglé ne doit pas dépasser ce qui est dû."""
    dossiers = (
        Enrollment.objects.select_related('student', 'session__course')
        .annotate(regle=Sum('payments__amount',
                            filter=Q(payments__status=Payment.Status.COMPLETED)))
        .filter(regle__gt=F('net_amount'))
    )
    return [
        (f'{e.student.display_label} — {e.session.course.title}',
         f'réglé {e.regle} > net dû {e.net_amount} (écart {e.regle - e.net_amount})')
        for e in dossiers.order_by('student__last_name')
    ]


def dossiers_doublons():
    """Un étudiant ne tient pas deux dossiers actifs sur la même formation."""
    lignes = (
        Enrollment.objects.filter(status=Enrollment.Status.ACTIVE)
        .values('student', 'session__course')
        .annotate(nb=Count('id')).filter(nb__gt=1)
        .order_by('student', 'session__course')
    )
    entetes = []
    for ligne in lignes:
        etudiant = User.objects.get(pk=ligne['student']).display_label
        formation = Course.objects.get(pk=ligne['session__course']).title
        entetes.append((f'{etudiant} — {formation}',
                        f'{ligne["nb"]} inscriptions actives sur cette formation'))
    return entetes


def dates_futures():
    """Une écriture ou un paiement daté après aujourd'hui ne peut pas être en caisse."""
    maintenant = timezone.now()
    lignes = [
        (p.reference, f'paiement de {p.amount} daté du {_date(p.paid_at)}')
        for p in Payment.objects.filter(
            status=Payment.Status.COMPLETED, paid_at__gt=maintenant).order_by('paid_at')
    ]
    lignes += [
        (t.reference, f'écriture de {t.amount} datée du {_date(t.occurred_at)}')
        for t in CashTransaction.objects.filter(
            status=CashTransaction.Status.VALIDATED,
            occurred_at__gt=maintenant).order_by('occurred_at')
    ]
    return lignes


def mensualites_sans_mois():
    """Une mensualité réglée dit quel mois elle solde."""
    return [
        (p.reference, f'{p.amount} · {_date(p.paid_at)} · '
                      f'{p.enrollment.student.display_label}')
        for p in Payment.objects.filter(
            motif=Payment.Motif.MONTHLY, period_month__isnull=True
        ).select_related('enrollment__student').order_by('paid_at')
    ]


def soldes_sous_plancher():
    """Le solde d'une caisse ne descend pas sous son découvert autorisé."""
    lignes = []
    for caisse in CashAccount.objects.filter(active=True):
        plancher = -caisse.overdraft_limit
        if caisse.balance < plancher:
            lignes.append((caisse.name,
                           f'solde {caisse.balance} < plancher {plancher}'))
    return lignes


def comptes_sans_dossier():
    """Un compte étudiant actif a au moins un dossier d'inscription."""
    sans = (
        User.objects.filter(roles__key=RoleKey.ETUDIANT,
                            account_status=AccountStatus.ACTIVE)
        .exclude(enrollments__isnull=False).distinct()
        .order_by('last_name', 'first_name')
    )
    return [(u.display_label, 'compte actif sans aucune inscription') for u in sans]


def presences_orphelines():
    """Une présence se rattache à un dossier qui existe encore."""
    return [
        (str(a.id), f'{_date(a.date)} · statut {a.status} · dossier absent')
        for a in Attendance.objects.filter(enrollment__isnull=True).order_by('date')
    ]


def groupes_sans_formateur():
    """Un groupe qui doit enseigner n'a personne pour le faire.

    Ce point est un signalement : rien n'est faux dans les tables, mais
    l'espace des étudiants inscrits y restera vide tant qu'aucun formateur
    n'est affecté. Les écrans refusent déjà cette écriture ; le contrôle la
    retrouve quand elle vient d'un import ou d'une saison antérieure.
    """
    return [
        (f'{g.course.title} — {g.starts_at:%d/%m/%Y}',
         f'statut {g.get_status_display()} · '
         f'{g.enrollments.count()} inscrit(s) · aucun formateur')
        for g in groupes.sans_formateur()
    ]


def journal_sur_entites_absentes():
    """Le journal d'audit cite des entités qui ne sont plus en base."""
    lignes = []
    types = (AuditLog.objects.exclude(entity_type='')
             .order_by().values_list('entity_type', flat=True).distinct())
    for type_entite in sorted(types):
        modele = MODELES.get(type_entite)
        if modele is None:
            continue
        champ_cle = modele._meta.pk
        exploitables, hors_format = [], []
        for identifiant in (AuditLog.objects.filter(entity_type=type_entite)
                            .order_by().values_list('entity_id', flat=True).distinct()):
            try:
                exploitables.append(str(champ_cle.to_python(identifiant)))
            except (ValidationError, ValueError, TypeError):
                # Une référence qui ne ressemble pas à une clé n'est pas une
                # entité disparue : c'est la trace elle-même qui est douteuse.
                hors_format.append(identifiant)
        connues = {
            str(cle) for cle in
            modele.objects.filter(pk__in=exploitables).values_list('pk', flat=True)
        } if exploitables else set()
        for identifiant in sorted(set(exploitables) - connues):
            lignes.append((f'{type_entite}:{identifiant}',
                           'trace du journal sans entité correspondante'))
        for identifiant in sorted(hors_format):
            lignes.append((f'{type_entite}:{identifiant}',
                           "clé d'entité dans un format que le modèle ne connaît pas"))
    return lignes


CONTROLES = [
    ('ECRITURE_RECETTE_SANS_PAIEMENT',
     'Une recette validée en caisse sans paiement d\'étudiant correspondant.',
     ecritures_recette_sans_paiement),
    ('PAIEMENT_SANS_ECRITURE',
     'Un paiement effectué sans écriture de caisse correspondante.',
     paiements_sans_ecriture),
    ('PAIEMENT_ATTEND_CAISSIE',
     'Un paiement encore en attente dont la caisse a déjà reçu l\'écriture validée.',
     paiements_en_attente_ecritures_validees),
    ('TRANSFERT_INCOMPLET',
     'Un transfert validé sans compte de destination, ou sur sa propre caisse.',
     transferts_incomplets),
    ('ECRITURE_SANS_COMPTE',
     'Une écriture de caisse qui ne rattache à aucune caisse.',
     ecritures_sans_compte),
    ('NET_INCOHERENT',
     'Le net dû d\'un dossier différent du tarif moins la remise.',
     nets_incoherents),
    ('REMISE_SUPERIEURE_TARIF',
     'Une remise plus élevée que le tarif qu\'elle est censée réduire.',
     remises_superieures_au_tarif),
    ('TROPERCU',
     'Un dossier réglé au-delà du montant net dû.',
     trop_perçus),
    ('DOSSIER_DOUBLON',
     'Deux inscriptions actives du même étudiant sur la même formation.',
     dossiers_doublons),
    ('DATE_FUTURE',
     'Un encaissement ou une écriture daté après aujourd\'hui.',
     dates_futures),
    ('MENSUALITE_SANS_MOIS',
     'Une mensualité réglée qui ne dit pas quel mois elle solde.',
     mensualites_sans_mois),
    ('SOLDE_SOUS_PLANCHER',
     'Un solde de caisse descendu sous le découvert autorisé du compte.',
     soldes_sous_plancher),
    ('COMPTE_ACTIF_SANS_DOSSIER',
     'Un compte étudiant actif sans aucun dossier d\'inscription.',
     comptes_sans_dossier),
    ('PRESENCE_ORPHELINE',
     'Une présence qui ne rattache à aucun dossier.',
     presences_orphelines),
    ('JOURNAL_ENTITE_ABSENTE',
     'Une ligne du journal d\'audit qui cite une entité disparue — le journal '
     'garde la trace après une suppression, ce point est un signalement, pas un refus.',
     journal_sur_entites_absentes, True),
    ('GROUPE_SANS_FORMATEUR',
     'Un groupe en préparation ou en cours sans formateur : le contenu n\'y '
     'parviendra pas. Ce point est un signalement, pas un refus.',
     groupes_sans_formateur, True),
]


def controler(codes=None) -> list:
    """Court les contrôles, dans l'ordre, et rend ceux qui ont quoi à dire."""
    retenus = ([c for c in CONTROLES if c[0] in set(codes)] if codes
               else CONTROLES)
    relevés = []
    for controle in retenus:
        code, regle, fonction = controle[:3]
        information = controle[3] if len(controle) > 3 else False
        relevés.append(Constat(code=code, regle=regle,
                               lignes=list(fonction()),
                               information=information))
    return relevés
