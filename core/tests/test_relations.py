"""Tests de la cohérence des relations entre tables : la mesure, puis le portique.

Chaque contrôle de `core.relations` est éprouvé deux fois : une base saine ne
doit rien signaler, et une incohérence semée doit être nommée par le bon code.
Les incohérences sont écrites par l'ORM, jamais par les écrans : ce que ces
tests vérifient, c'est que la mesure voit ce qu'un script ou l'administration
aurait laissé passer.
"""
import datetime as dt
import io
import json
import uuid

from django.core.management import CommandError, call_command
from django.utils import timezone

from core.models import (
    Attendance, AuditLog, CashTransaction, CourseSession, Enrollment, Payment,
    RoleKey, User,
)
from core import relations

from .base import BusinessTestBase


def ecarts(constats):
    """Les seuls constats qui refusent la livraison : hors signalements."""
    return {c.code: c.nombre for c in constats if not c.information and c.nombre}


class RelationsBase(BusinessTestBase):
    def controler(self):
        return relations.controler()

    def dossier(self, etudiant, session, **champs):
        data = {
            'status': Enrollment.Status.ACTIVE,
            'tariff_amount': 100000,
            'discount_amount': 0,
            'net_amount': 100000,
        }
        data.update(champs)
        return Enrollment.objects.create(student=etudiant, session=session, **data)

    def deuxieme_etudiant(self, email='second@test.local'):
        return self.make_user(RoleKey.ETUDIANT, email)


class RelationsBaseSaineTest(RelationsBase):
    def test_une_base_coherente_ne_signale_rien(self):
        self.assertEqual(ecarts(self.controler()), {})

    def test_seize_controles_sont_pose(self):
        self.assertEqual(len(relations.CONTROLES), 16)
        self.assertEqual(
            len({code for code, _r, *_x in relations.CONTROLES}), 16)

    def test_le_service_ne_rien_ecrit_dans_la_base(self):
        """Mesurer n'est pas corriger : le comptage reste la seule conséquence."""
        avant = (Payment.objects.count(), CashTransaction.objects.count(),
                 Enrollment.objects.count(), AuditLog.objects.count())
        self.controler()
        apres = (Payment.objects.count(), CashTransaction.objects.count(),
                 Enrollment.objects.count(), AuditLog.objects.count())
        self.assertEqual(avant, apres)


class RelationsRecettesTest(RelationsBase):
    def test_une_recette_etudiante_sans_paiement_est_nommee(self):
        CashTransaction.objects.create(
            tx_type=CashTransaction.Type.IN,
            label='Mensualité sans dossier', amount=25000, account=self.cash,
            status=CashTransaction.Status.VALIDATED,
            category=self.income_category,
        )
        self.assertEqual(ecarts(self.controler()),
                         {'ECRITURE_RECETTE_SANS_PAIEMENT': 1})

    def test_une_recette_d_autre_origine_n_est_pas_une_recette_etudiante(self):
        """Seule la catégorie des paiements d'étudiants promet un dossier."""
        CashTransaction.objects.create(
            tx_type=CashTransaction.Type.IN,
            label='Subvention', amount=500000, account=self.cash,
            status=CashTransaction.Status.VALIDATED,
        )
        self.assertEqual(ecarts(self.controler()), {})

    def test_un_paiement_effectue_sans_ecriture_est_nomme(self):
        Payment.objects.create(
            enrollment=self.enrollment, amount=20000,
            method=Payment.Method.CASH, status=Payment.Status.COMPLETED,
            motif=Payment.Motif.MONTHLY, period_year=self.today.year,
            period_month=6,
        )
        self.assertEqual(ecarts(self.controler()), {'PAIEMENT_SANS_ECRITURE': 1})

    def test_un_paiement_en_attente_deja_en_caisse_est_nomme(self):
        paiement = Payment.objects.create(
            enrollment=self.enrollment, amount=20000,
            method=Payment.Method.CASH, status=Payment.Status.PENDING,
        )
        écriture = CashTransaction.objects.create(
            tx_type=CashTransaction.Type.IN,
            label='Encaissement à valider', amount=20000, account=self.cash,
            status=CashTransaction.Status.VALIDATED,
            category=self.income_category,
        )
        paiement.transaction = écriture
        paiement.save(update_fields=['transaction'])
        self.assertEqual(ecarts(self.controler()), {'PAIEMENT_ATTEND_CAISSIE': 1})

    def test_un_transfert_sans_destination_est_nomme(self):
        CashTransaction.objects.create(
            tx_type=CashTransaction.Type.IN,
            label='Approvisionnement', amount=100000, account=self.cash,
            status=CashTransaction.Status.VALIDATED,
        )
        CashTransaction.objects.create(
            tx_type=CashTransaction.Type.TRANSFER,
            label='Transfert boîteux', amount=50000, account=self.cash,
            status=CashTransaction.Status.VALIDATED,
        )
        self.assertEqual(ecarts(self.controler()), {'TRANSFERT_INCOMPLET': 1})


class RelationsDossiersTest(RelationsBase):
    def test_un_net_different_du_tarif_moins_la_remise_est_nomme(self):
        etudiant = self.deuxieme_etudiant()
        self.dossier(etudiant, self.session, discount_amount=10000, net_amount=50000)
        lignes = {c.code: c.lignes for c in self.controler()}['NET_INCOHERENT']
        self.assertEqual(len(lignes), 1)

    def test_une_remise_plus_forte_que_le_tarif_est_nommee(self):
        etudiant = self.deuxieme_etudiant('remise@test.local')
        self.dossier(etudiant, self.session, tariff_amount=30000,
                     discount_amount=40000, net_amount=0)
        # Une remise démesurée ne laisse aucun net cohérent possible : les deux
        # règles tombent en même temps, et la mesure nomme les deux.
        self.assertEqual(ecarts(self.controler()),
                         {'REMISE_SUPERIEURE_TARIF': 1, 'NET_INCOHERENT': 1})

    def test_un_dossier_regle_au_del_du_net_est_nomme(self):
        Payment.objects.create(
            enrollment=self.enrollment, amount=95000,
            method=Payment.Method.CASH, status=Payment.Status.COMPLETED,
            transaction=CashTransaction.objects.create(
                tx_type=CashTransaction.Type.IN, label='Recette',
                amount=95000, account=self.cash,
                status=CashTransaction.Status.VALIDATED,
                category=self.income_category,
            ),
        )
        self.assertEqual(ecarts(self.controler()), {'TROPERCU': 1})

    def test_deux_dossiers_actifs_sur_la_meme_formation_sont_nommés(self):
        autre_session = CourseSession.objects.create(
            course=self.course,
            starts_at=self.today + dt.timedelta(days=5),
            ends_at=self.today + dt.timedelta(days=95),
            status=CourseSession.Status.ACTIVE,
        )
        self.dossier(self.etudiant, autre_session)
        self.assertEqual(ecarts(self.controler()), {'DOSSIER_DOUBLON': 1})

    def test_un_dossier_termine_ne_compte_pas_comme_double_emploi(self):
        autre_session = CourseSession.objects.create(
            course=self.course,
            starts_at=self.today + dt.timedelta(days=5),
            ends_at=self.today + dt.timedelta(days=95),
            status=CourseSession.Status.ACTIVE,
        )
        self.dossier(self.etudiant, autre_session,
                     status=Enrollment.Status.COMPLETED)
        self.assertEqual(ecarts(self.controler()), {})

    def test_un_compte_etudiant_actif_sans_dossier_est_signale(self):
        self.deuxieme_etudiant('sansdossier@test.local')
        self.assertEqual(ecarts(self.controler()), {'COMPTE_ACTIF_SANS_DOSSIER': 1})


class RelationsDatesTest(RelationsBase):
    def test_un_paiement_date_demain_est_nomme(self):
        Payment.objects.create(
            enrollment=self.enrollment, amount=10000,
            method=Payment.Method.CASH, status=Payment.Status.COMPLETED,
            paid_at=timezone.now() + dt.timedelta(days=2),
        )
        # Sans écriture au passage : la date n'est pas le seul écart de cette ligne.
        self.assertEqual(ecarts(self.controler()),
                         {'DATE_FUTURE': 1, 'PAIEMENT_SANS_ECRITURE': 1})

    def test_une_ecriture_datee_plus_tard_est_nomme(self):
        CashTransaction.objects.create(
            tx_type=CashTransaction.Type.IN, label='Recette de demain',
            amount=100000, account=self.cash,
            occurred_at=timezone.now() + dt.timedelta(days=3),
            status=CashTransaction.Status.VALIDATED,
            category=self.income_category,
        )
        self.assertEqual(ecarts(self.controler()),
                         {'DATE_FUTURE': 1, 'ECRITURE_RECETTE_SANS_PAIEMENT': 1})

    def test_une_mensualite_sans_mois_regle_est_nommee(self):
        Payment.objects.create(
            enrollment=self.enrollment, amount=25000,
            method=Payment.Method.CASH, status=Payment.Status.COMPLETED,
            motif=Payment.Motif.MONTHLY,
        )
        self.assertEqual(ecarts(self.controler()),
                         {'MENSUALITE_SANS_MOIS': 1, 'PAIEMENT_SANS_ECRITURE': 1})


class RelationsCaisseTest(RelationsBase):
    def test_un_solde_passe_sous_le_plancher_est_nomme(self):
        """Le garde du modèle refuse cette écriture : un script, non.

        On passe par `update()` pour montrer que la mesure, elle, ne se
        laisse pas attendrir par la porte d'entrée.
        """
        from core.models import CashAccount
        CashAccount.objects.filter(pk=self.cash.pk).update(opening_balance=-5000)
        self.assertEqual(ecarts(self.controler()), {'SOLDE_SOUS_PLANCHER': 1})

    def test_un_decouvert_autorise_n_est_un_ecart_pour_rien(self):
        from core.models import CashAccount
        CashAccount.objects.filter(pk=self.cash.pk).update(
            opening_balance=-5000, overdraft_limit=5000)
        self.assertEqual(ecarts(self.controler()), {})

    def test_une_presence_orpheline_ne_traverse_pas_le_service(self):
        """Le champ est obligatoire en base : le contrôle reste là, muet."""
        Attendance.objects.create(
            enrollment=self.enrollment, date=self.today,
            status=Attendance.Status.PRESENT, recorded_by=self.formateur,
        )
        self.assertEqual(ecarts(self.controler()), {})
        self.assertEqual(relations.presences_orphelines(), [])


class RelationsJournalTest(RelationsBase):
    def test_une_trace_sur_une_entite_disparue_reste_un_signalement(self):
        AuditLog.objects.create(action='PAYMENT_DELETE', entity_type='Payment',
                                entity_id=str(uuid.uuid4()))
        constats = self.controler()
        self.assertEqual(ecarts(constats), {})
        signalement = [c for c in constats if c.information][0]
        self.assertEqual(signalement.nombre, 1)
        self.assertEqual(signalement.code, 'JOURNAL_ENTITE_ABSENTE')

    def test_une_cle_de_format_inconnu_est_nommee_sans_faire_ecarter_la_base(self):
        AuditLog.objects.create(action='BATCH_IMPORT', entity_type='Payment',
                                entity_id='feuille-2026')
        constats = self.controler()
        self.assertEqual(ecarts(constats), {})
        lignes = [c for c in constats if c.information][0].lignes
        self.assertIn('format', lignes[0][1])

    def test_le_journal_d_un_reglage_d_ecran_ne_jamais_un_ecart(self):
        AuditLog.objects.create(action='PLATFORM_SETTINGS_EDIT',
                                entity_type='PlatformSetting', entity_id='1')
        self.assertEqual(ecarts(self.controler()), {})


class RelationsGroupesTest(RelationsBase):
    """Un groupe qui doit enseigner sans formateur : mesuré, pas refusé ici."""

    def constat(self):
        return [c for c in self.controler()
                if c.code == 'GROUPE_SANS_FORMATEUR'][0]

    def test_un_groupe_en_cours_sans_formateur_est_nomme(self):
        self.session.formateurs.clear()
        self.assertEqual(self.constat().nombre, 1)
        self.assertTrue(self.constat().information)
        ref, detail = self.constat().lignes[0]
        self.assertIn(self.course.title, ref)
        self.assertIn('aucun formateur', detail)

    def test_le_signalement_ne_compte_pas_comme_ecart(self):
        """Le contenu reste à poser : les tables, elles, sont cohérentes."""
        self.session.formateurs.clear()
        self.assertEqual(ecarts(self.controler()), {})

    def test_un_groupe_termine_n_est_pas_reclame(self):
        self.session.formateurs.clear()
        CourseSession.objects.filter(pk=self.session.pk).update(
            status=CourseSession.Status.COMPLETED)
        self.assertEqual(self.constat().nombre, 0)

    def test_l_affectation_efface_le_signalement(self):
        self.session.formateurs.clear()
        self.assertEqual(self.constat().nombre, 1)
        self.session.formateurs.add(self.formateur)
        self.assertEqual(self.constat().nombre, 0)


class RelationsCommandeTest(RelationsBase):
    def test_le_portique_passe_sur_une_base_saine(self):
        sortie = io.StringIO()
        call_command('verifier_relations', maxi=0, stdout=sortie)
        self.assertIn('Cohérence acceptée', sortie.getvalue())

    def test_le_portique_refuse_des_qu_un_ecart_parait(self):
        Payment.objects.create(
            enrollment=self.enrollment, amount=10000,
            method=Payment.Method.CASH, status=Payment.Status.COMPLETED,
        )
        with self.assertRaises(CommandError) as refuse:
            call_command('verifier_relations', maxi=0, stdout=io.StringIO())
        # Le refus nomme les codes fautifs : un portique muet ne dit rien à qui le lit.
        self.assertIn('PAIEMENT_SANS_ECRITURE', str(refuse.exception))

    def test_le_seuil_accepte_autant_d_ecarts_qu_on_le_laisse(self):
        Payment.objects.create(
            enrollment=self.enrollment, amount=10000,
            method=Payment.Method.CASH, status=Payment.Status.COMPLETED,
        )
        sortie = io.StringIO()
        call_command('verifier_relations', maxi=1, stdout=sortie)
        self.assertIn('1 écart(s)', sortie.getvalue())

    def test_un_seul_code_peut_etre_releve_seul(self):
        Payment.objects.create(
            enrollment=self.enrollment, amount=10000,
            method=Payment.Method.CASH, status=Payment.Status.COMPLETED,
        )
        CashTransaction.objects.create(
            tx_type=CashTransaction.Type.IN, label='Recette sans dossier',
            amount=10000, account=self.cash,
            status=CashTransaction.Status.VALIDATED,
            category=self.income_category,
        )
        sortie = io.StringIO()
        call_command('verifier_relations', maxi=1, code=['PAIEMENT_SANS_ECRITURE'],
                     stdout=sortie)
        compte = sortie.getvalue()
        self.assertIn('1 contrôles', compte)
        self.assertNotIn('ECRITURE_RECETTE_SANS_PAIEMENT', compte)

    def test_le_json_rend_les_memes_chiffres_que_lecran(self):
        CashTransaction.objects.create(
            tx_type=CashTransaction.Type.IN, label='Recette sans dossier',
            amount=10000, account=self.cash,
            status=CashTransaction.Status.VALIDATED,
            category=self.income_category,
        )
        sortie = io.StringIO()
        call_command('verifier_relations', maxi=5, en_json=True, stdout=sortie)
        rendu = json.loads(sortie.getvalue())
        self.assertEqual(rendu['total'], 1)
        self.assertEqual(rendu['constats'][0]['code'],
                         'ECRITURE_RECETTE_SANS_PAIEMENT')
        self.assertEqual(
            sum(c['nombre'] for c in rendu['constats'] if c['information']), 0)

    def test_les_lignes_donnees_sont_bornees(self):
        for i in range(4):
            Payment.objects.create(
                enrollment=self.enrollment, amount=1000 + i,
                method=Payment.Method.CASH, status=Payment.Status.COMPLETED,
            )
        sortie = io.StringIO()
        call_command('verifier_relations', maxi=99, lignes=2, stdout=sortie)
        compte = sortie.getvalue()
        self.assertIn('PAIEMENT_SANS_ECRITURE — 4 ligne(s)', compte)
        self.assertIn('2 autre(s)', compte)

    def test_la_lecture_de_la_base_ne_depend_pas_des_reglages_pose(self):
        """Un changement de nom ou de devise ne crée ni n'efface un écart."""
        from core.models import PlatformSetting
        reglages = PlatformSetting.objects.get()
        reglages.nom = 'Centre des Langues'
        reglages.devise = 'CDF'
        reglages.seuil_alerte = 65
        reglages.save()
        self.assertEqual(ecarts(self.controler()), {})
        self.assertIsInstance(User.objects.get(pk=self.etudiant.pk), User)
