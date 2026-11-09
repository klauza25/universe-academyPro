"""Purge les donnees hors classeurs Google avant un deploiement local.

La commande conserve les comptes super-administrateur, les comptes lies aux
inscriptions importees, et les formations, groupes, inscriptions, paiements et
ecritures identifies par les marqueurs des importeurs.

    python manage.py purger_donnees_fictives          # previsualisation
    python manage.py purger_donnees_fictives --ecrire # copie SQLite puis purge
"""
from __future__ import annotations

from django.contrib.admin.models import LogEntry
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from core.eleves_import import MARQUE as MARQUE_CLASSEURS
from core.feuille_import import MARQUE_FEUILLE
from core.models import (
    AccessEvent, AccessRequest, Attendance, AuditLog, CashAccount,
    CashClosure, CashTransaction, Certificate, Contact, Course, CourseSession,
    Destination, Enrollment, Expense, Lesson, Module, Notification, Payment,
    PlatformSetting, Prospect, ProspectFollowUp, Resource, ResourceFeedback,
    RoleKey, ScholarshipApplication, ScholarshipDocument, SessionRecord,
    StudentDocument, StudentSessionNote, TransactionCategory, User, Visit,
)
from core.programme_import import MARQUE as MARQUE_FORMATIONS
from core.sauvegarde import sauvegarder_base


class Command(BaseCommand):
    help = ('Supprime les donnees non issues des classeurs Google, en conservant '
            'les super-administrateurs et la configuration.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--ecrire', action='store_true',
            help='Sauvegarder la base SQLite puis effectuer la purge.',
        )

    def handle(self, *args, **options):
        if options['ecrire']:
            moteur = self.get_db_engine()
            if 'sqlite3' not in moteur:
                raise CommandError(
                    'La purge exige une base SQLite pour garantir une copie '
                    'de securite automatique.'
                )
            copie = sauvegarder_base()
            if copie is None:
                raise CommandError('La copie de securite SQLite a echoue.')

        plan = self._plan()
        self._afficher_plan(plan, options['ecrire'])
        if not options['ecrire']:
            return

        with transaction.atomic():
            plan = self._plan()
            self._supprimer(plan)

        self.stdout.write(self.style.SUCCESS('Purge terminee.'))
        self.stdout.write(f'Copie de securite : {copie}')
        self._afficher_conservation(plan)

    @staticmethod
    def get_db_engine():
        from django.conf import settings
        return settings.DATABASES['default']['ENGINE']

    @staticmethod
    def _plan():
        superadmins = User.objects.filter(
            is_superuser=True, roles__key=RoleKey.SUPER_ADMIN,
        ).distinct()
        if not superadmins.exists():
            raise CommandError(
                'Aucun compte super-administrateur verifiable : purge annulee.'
            )

        paiements_marques = Payment.objects.filter(
            Q(note__contains=MARQUE_CLASSEURS)
            | Q(note__contains=MARQUE_FEUILLE)
        )
        inscriptions_conservees = Enrollment.objects.filter(
            Q(notes__contains=MARQUE_CLASSEURS)
            | Q(payments__in=paiements_marques)
        ).distinct()
        paiements_conserves = Payment.objects.filter(
            Q(enrollment__in=inscriptions_conservees)
            | Q(pk__in=paiements_marques)
        ).distinct()
        groupes_conserves = CourseSession.objects.filter(
            Q(schedule__contains=MARQUE_CLASSEURS)
            | Q(enrollments__in=inscriptions_conservees)
        ).distinct()
        formations_conservees = Course.objects.filter(
            Q(description__contains=MARQUE_FORMATIONS)
            | Q(sessions__in=groupes_conserves)
        ).distinct()
        utilisateurs_conserves = User.objects.filter(
            Q(pk__in=superadmins.values('pk'))
            | Q(enrollments__in=inscriptions_conservees)
        ).distinct()
        transactions_marquees = CashTransaction.objects.filter(
            Q(note__contains=MARQUE_CLASSEURS)
            | Q(description__contains=MARQUE_CLASSEURS)
            | Q(note__contains=MARQUE_FEUILLE)
            | Q(description__contains=MARQUE_FEUILLE)
        )
        transactions_conservees = CashTransaction.objects.filter(
            Q(pk__in=transactions_marquees.values('pk'))
            | Q(pk__in=paiements_conserves.exclude(
                transaction_id__isnull=True
            ).values('transaction_id'))
        ).distinct()

        a_supprimer = [
            ('demandes_acces', AccessRequest.objects.all()),
            ('evenements_acces', AccessEvent.objects.all()),
            ('presences', Attendance.objects.all()),
            ('journal_audit', AuditLog.objects.all()),
            ('journal_admin', LogEntry.objects.all()),
            ('sessions_connexion', Session.objects.all()),
            ('clotures_caisse', CashClosure.objects.all()),
            ('certificats', Certificate.objects.all()),
            ('depenses', Expense.objects.all()),
            ('notifications', Notification.objects.all()),
            ('prospects_relances', ProspectFollowUp.objects.all()),
            ('prospects', Prospect.objects.all()),
            ('visites', Visit.objects.all()),
            ('contacts', Contact.objects.all()),
            ('ressources_retours', ResourceFeedback.objects.all()),
            ('ressources', Resource.objects.all()),
            ('documents_bourses', ScholarshipDocument.objects.all()),
            ('demandes_bourses', ScholarshipApplication.objects.all()),
            ('documents_etudiants', StudentDocument.objects.all()),
            ('notes_seances_etudiants', StudentSessionNote.objects.all()),
            ('seances_realisees', SessionRecord.objects.all()),
            ('lecons', Lesson.objects.all()),
            ('modules', Module.objects.all()),
            ('paiements', Payment.objects.exclude(
                pk__in=paiements_conserves.values('pk')
            )),
            ('ecritures_caisse', CashTransaction.objects.exclude(
                pk__in=transactions_conservees.values('pk')
            )),
            ('inscriptions', Enrollment.objects.exclude(
                pk__in=inscriptions_conservees.values('pk')
            )),
            ('groupes', CourseSession.objects.exclude(
                pk__in=groupes_conserves.values('pk')
            )),
            ('formations', Course.objects.exclude(
                pk__in=formations_conservees.values('pk')
            )),
            ('utilisateurs', User.objects.exclude(
                pk__in=utilisateurs_conserves.values('pk')
            )),
        ]
        return {
            'superadmins': superadmins,
            'users': utilisateurs_conserves,
            'enrollments': inscriptions_conservees,
            'payments': paiements_conserves,
            'transactions': transactions_conservees,
            'sessions': groupes_conserves,
            'courses': formations_conservees,
            'delete': a_supprimer,
        }

    def _afficher_plan(self, plan, ecrire):
        titre = 'Purge en cours' if ecrire else 'Previsualisation : aucune suppression'
        self.stdout.write(self.style.MIGRATE_HEADING(titre))
        self._afficher_conservation(plan)
        self.stdout.write('Donnees a supprimer :')
        for nom, queryset in plan['delete']:
            self.stdout.write(f'  {nom} : {queryset.count()}')
        self.stdout.write(
            'La configuration (roles, permissions, reglages, caisses, categories '
            'et destinations) sera conservee.'
        )

    def _afficher_conservation(self, plan):
        self.stdout.write('Donnees conservees :')
        for cle, nom in (
            ('superadmins', 'super-administrateurs'),
            ('users', 'utilisateurs lies aux classeurs et super-administrateurs'),
            ('courses', 'formations'),
            ('sessions', 'groupes'),
            ('enrollments', 'inscriptions'),
            ('payments', 'paiements'),
            ('transactions', 'ecritures de caisse'),
        ):
            self.stdout.write(f'  {nom} : {plan[cle].count()}')

    @staticmethod
    def _supprimer(plan):
        for nom, queryset in plan['delete']:
            queryset.delete()
