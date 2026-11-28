"""Tests de la vague 2 : ce que le classeur d'élèves devient en base, et ce qui ne le devient pas.

Les règles de préparation sont des fonctions pures de ``core.eleves_import`` ; la commande
``importer_etudiants`` est testée avec un analyseur de fortune, sans classeur déposé.
"""
import datetime as dt
import io
from dataclasses import dataclass, field

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from core import data_tools as outils
from core import eleves_import as import_eleves
from core.utils import compte_reel_a_paiements, doublon_importe
from core.models import (
    AccountStatus, CashAccount, CashTransaction, Course, CourseSession, Enrollment,
    Payment, Role, RoleKey, TransactionCategory, User,
)

AUJOURD_HUI = dt.date(2026, 11, 2)


@dataclass
class Ligne:
    """Ce que ``data_tools.extraire_ligne`` rend pour une ligne d'onglet."""
    onglet: str = 'Anglais'
    bloc: str = 'Anglais !A'
    ligne: int = 3
    nom: str = 'LOUAMBA Brivah'
    date_inscription: dt.date | None = None
    frais_inscription: int | None = 10000
    mensuel_prevu: int | None = 25000
    mois: list = field(default_factory=list)
    commentaire: str = ''
    option: str = ''
    cout_total: int | None = None
    duree: str = ''

    def __post_init__(self):
        self.cle = outils.cle_personne(self.nom)


def une_case_mois(numero=11, libelle='NOVEMBRE', montant=25000, statut='ok', brut=None):
    return (numero, libelle, montant, statut, brut if brut is not None else (brut or ''))


def fiche(complet='LOUAMBA Brivah', nom='LOUAMBA', prenom='Brivah', telephone='067813740',
          email='brivah@test.local', adresse='Moungali', formation='Anglais',
          date=dt.date(2026, 10, 12), classeur='Gestion des étudiants.xlsx', ligne=4):
    return {'classeur': classeur, 'ligne': ligne, 'complet': complet, 'nom': nom,
            'prenom': prenom, 'cle': outils.cle_personne(complet), 'telephone': telephone,
            'email': email, 'adresse': adresse, 'formation': formation, 'date': date,
            'date_statut': 'ok'}


class Analyse:
    """Le minimum attendu d'un ``analyser_donnees`` déjà passé par ``collecter``."""

    def __init__(self, lignes=(), fiches=(), stats=(), appariement=None):
        self.inaccessibles = []
        self.contenu = {'Gestion des étudiants.xlsx': {}}
        self.suivis = {'inscriptions': list(lignes),
                       'stats': list(stats) or [('Gestion des étudiants.xlsx',
                                                 lignes[0].onglet if lignes else 'Anglais',
                                                 1, len(lignes), [])]}
        self.base = {'lignes': list(fiches)}
        self._appariement = lambda: dict(appariement or {})


TARIFS = {'Anglais': {'frais': 225000, 'duree': 9, 'mensuel': 25000},
          'Bureautique': {'frais': 180000, 'duree': 9, 'mensuel': 20000}}


def appariement(**supplements):
    rendu = {'anglais': ('Anglais', 'importee')}
    rendu.update(supplements)
    return rendu


# ---------------------------------------------------------------------------
class LecturesDuClasseurTests(SimpleTestCase):
    def test_le_nom_se_coupe_ou_la_casse_le_fait(self):
        self.assertEqual(import_eleves.decouper_nom('LOUAMBA Brivah'), ('LOUAMBA', 'Brivah'))
        self.assertEqual(import_eleves.decouper_nom('GNEKOUMOU LIBALA L'),
                         ('GNEKOUMOU LIBALA L', ''))
        # Rien ne distingue le nom du prénom : tout part dans le nom, le prénom reste à saisir.
        self.assertEqual(import_eleves.decouper_nom('louamba brivah'), ('louamba brivah', ''))
        self.assertEqual(import_eleves.decouper_nom(''), ('', ''))

    def test_un_numero_de_telephone_se_rapproche_quelle_que_soit_sa_forme(self):
        for valeur in ('+242 06 78 13 74 0', '00242067813740', '067813740', '06.78.13.74.0'):
            self.assertEqual(import_eleves.normaliser_telephone(valeur), '067813740', valeur)
        self.assertEqual(import_eleves.normaliser_telephone('0678'), '')

    def test_une_case_de_telephone_peut_cacher_deux_adresses(self):
        plan = import_eleves.preparer(
            Analyse(fiches=[fiche(email='a@x.com b@y.com')]), TARIFS, [], appariement(),
            'Gestion des étudiants.xlsx', AUJOURD_HUI)
        self.assertEqual(plan.comptes[0].email, 'a@x.com')

    def test_une_adresse_qui_n_est_pas_une_adresse_ne_sert_pas_d_identifiant(self):
        self.assertFalse(import_eleves.adresse_valide('elemesarahpriscille@gmail.com   '
                                                      'sp.eleme@unesco.org'))
        self.assertFalse(import_eleves.adresse_valide('Formation en anglais et francais'))
        self.assertTrue(import_eleves.adresse_valide('Brivah.Test@X.COM'))

    def test_une_formation_non_terminee_n_est_pas_marquee_terminee(self):
        self.assertTrue(import_eleves.formation_terminee('formation terminée'))
        self.assertTrue(import_eleves.formation_terminee('Terminé Dernier mois non payé'))
        self.assertFalse(import_eleves.formation_terminee('non terminée'))
        self.assertFalse(import_eleves.formation_terminee('non treminée'))
        self.assertFalse(import_eleves.formation_terminee(''))

    def test_les_mois_se_comptent_a_partir_de_la_date_d_inscription(self):
        self.assertEqual(import_eleves.ajouter_mois(dt.date(2026, 1, 31), 1), dt.date(2026, 2, 28))
        self.assertEqual(import_eleves.ajouter_mois(dt.date(2024, 1, 31), 1), dt.date(2024, 2, 29))
        self.assertEqual(import_eleves.ajouter_mois(dt.date(2026, 11, 12), 9), dt.date(2027, 8, 12))


class PreparationDuPlanTests(SimpleTestCase):
    def plan(self, lignes, fiches=(), tarifs=None, existants=(), appariement_=None, classeur=''):
        return import_eleves.preparer(
            Analyse(lignes=lignes, fiches=fiches,
                    stats=[('Gestion des étudiants.xlsx', l.onglet, 1, 1, []) for l in lignes]),
            tarifs or TARIFS, list(existants), appariement_ or appariement(), classeur, AUJOURD_HUI)

    def test_une_ligne_devient_une_inscription_et_ses_paiements(self):
        ligne = Ligne(mois=[une_case_mois(11, 'NOVEMBRE', 25000)])
        plan = self.plan([ligne], [fiche()], classeur='Gestion des étudiants.xlsx')
        self.assertEqual(len(plan.inscriptions), 1)
        self.assertEqual(len(plan.groupes), 1)
        # Le seul encaissement importé est la mensualité, au montant lu dans la case.
        self.assertEqual([p.montant for p in plan.paiements], [25000])
        self.assertIn("frais d'inscription non importés", [e[0] for e in plan.ecarts])

    def test_le_mois_d_inscription_place_la_premiere_mensualite_de_l_annee_suivante(self):
        ligne = Ligne(date_inscription=dt.date(2025, 10, 20),
                      mois=[une_case_mois(11, 'NOVEMBRE', 25000), une_case_mois(1, 'JANVIER', 25000)])
        plan = self.plan([ligne], [fiche()])
        # L'historique est importé : un mois réglé avant novembre 2026 reste en base.
        jours = sorted(p.jour for p in plan.paiements if p.motif == 'Mensualité')
        self.assertEqual(jours, [dt.date(2025, 11, 1), dt.date(2026, 1, 1)])

    def test_un_chiffre_de_mois_futur_ne_vaut_pas_encaissement(self):
        """La grille annonce les mois à venir : elle ne prouve pas l'argent reçu.

        Une promotion ouverte en octobre 2026 avec des cases remplies jusqu'en
        avril 2027 écrivait cinq paiements datés dans le futur, donc un trop-perçu
        qui n'existait pas. La ligne se signale, elle ne s'écrit pas.
        """
        ligne = Ligne(date_inscription=dt.date(2026, 10, 15),
                      mois=[une_case_mois(12, 'DECEMBRE', 30000),
                            une_case_mois(1, 'JANVIER', 30000),
                            une_case_mois(4, 'AVRIL', 30000)])
        plan = self.plan([ligne], [fiche(date=dt.date(2026, 10, 15))])
        self.assertEqual(plan.paiements, [])
        self.assertIn("mensualité d'un mois non encore commencé",
                      [e[0] for e in plan.ecarts])
        signalees = [e[2] for e in plan.ecarts
                     if e[0] == "mensualité d'un mois non encore commencé"]
        self.assertEqual(len(signalees), 3)
        self.assertIn('AVRIL 2027', signalees[2])

    def test_les_frais_d_inscription_du_sheet_ne_sont_pas_importes(self):
        """Ils s'encaissent au guichet : le classeur ne crée pas d'écriture d'argent."""
        ligne = Ligne(date_inscription=dt.date(2026, 3, 5), frais_inscription=10000, mois=[])
        plan = self.plan([ligne], [fiche()])
        self.assertEqual(plan.paiements, [])
        signale = [e for e in plan.ecarts if e[0] == "frais d'inscription non importés"]
        self.assertEqual(len(signale), 1)
        self.assertIn('10 000 FCFA', signale[0][2])
        self.assertIn('à saisir manuellement', signale[0][2])

    def test_les_mois_historiques_sont_importes_au_montant_exact_du_sheet(self):
        """Même hors bande, la case est écrite telle quelle et l'écart est signalé."""
        ligne = Ligne(date_inscription=dt.date(2025, 9, 10), mois=[
            une_case_mois(10, 'OCTOBRE', 88000),
            une_case_mois(11, 'NOVEMBRE', 99999),
        ])
        plan = self.plan([ligne], [fiche()])
        self.assertEqual([(p.jour, p.montant) for p in plan.paiements], [
            (dt.date(2025, 10, 1), 88000),
            (dt.date(2025, 11, 1), 99999),
        ])
        self.assertEqual([e[0] for e in plan.ecarts].count(
            'mensualité du Sheet hors de la bande'), 2)

    def test_un_montant_dans_la_bande_mais_different_du_tarif_est_ecrit_sans_ecart(self):
        """Le tarif manuel ne remplace plus une case pourtant conforme à la bande."""
        ligne = Ligne(mois=[une_case_mois(11, 'NOVEMBRE', 20000)])
        plan = self.plan([ligne], [fiche()])
        self.assertEqual([p.montant for p in plan.paiements], [20000])
        types = [e[0] for e in plan.ecarts]
        self.assertNotIn('mensualité du Sheet hors de la bande', types)
        self.assertNotIn('montant du Sheet remplacé', types)

    def test_deux_blocs_d_un_onglet_sont_deux_promotions(self):
        plan = self.plan([
            Ligne(bloc='Anglais !A', nom='UN Eleve'),
            Ligne(bloc='Anglais !I', nom='DEUX Eleve'),
        ])
        self.assertEqual(len(plan.groupes), 2)
        self.assertEqual(len(plan.inscriptions), 2)

    def test_un_eleve_en_double_dans_le_meme_groupe_est_ignore_et_signale(self):
        plan = self.plan([
            Ligne(date_inscription=dt.date(2026, 9, 10),
                  nom='KIMBEMBU Grace', mois=[une_case_mois(10, 'OCTOBRE', 25000)]),
            Ligne(date_inscription=dt.date(2026, 9, 10),
                  nom='KIMBEMBU Grace', ligne=9, mois=[une_case_mois(11, 'NOVEMBRE', 25000)]),
        ])
        self.assertEqual(len(plan.inscriptions), 1)
        self.assertEqual(len(plan.paiements), 1)  # une seule mensualité reprise, aucun frais importé
        self.assertIn('élève en double dans le même groupe',
                      [type_ for type_, _o, _q in plan.ecarts])

    def test_un_intitule_seulement_ressemblant_ne_cree_rien(self):
        plan = self.plan([Ligne(onglet='FRANCAIS')],
                         appariement_=appariement(**{'francais': ('Francais A2', 'probable')}))
        self.assertEqual(plan.inscriptions, [])
        self.assertEqual(plan.ecartes[0][0], 'formation non confirmée')

    def test_le_registre_des_anciens_se_rattache_par_l_option(self):
        """Le onglet est un registre, mais chaque ligne nomme sa formation dans OPTION."""
        ligne = Ligne(onglet='ANCIENS ETUDIANTS', option='ANGLAIS',
                      date_inscription=dt.date(2026, 7, 28))
        plan = self.plan([ligne], appariement_=appariement(
            **{'anciens etudiants': (None, 'registre')}))
        self.assertEqual(len(plan.inscriptions), 1)
        self.assertEqual(plan.groupes[0].titre, 'Anglais')
        self.assertEqual(plan.ecartes, [])

    def test_un_ancien_sans_option_est_signale_sans_rattachement(self):
        plan = self.plan([Ligne(onglet='ANCIENS ETUDIANTS', nom='IBOVI Sadie')],
                         appariement_=appariement(**{'anciens etudiants': (None, 'registre')}))
        self.assertEqual(plan.inscriptions, [])
        self.assertEqual(plan.ecartes[0][0], 'ancien sans formation précisée')

    def test_non_terminee_ne_passe_pas_en_dossier_termine(self):
        ligne = Ligne(onglet='ANCIENS ETUDIANTS', option='ANGLAIS',
                      commentaire='non treminée')
        plan = self.plan([ligne], appariement_=appariement(
            **{'anciens etudiants': (None, 'registre')}))
        self.assertEqual(plan.inscriptions[0].statut, 'ACTIVE')

    def test_une_formation_declaree_a_creer_est_prevue_sans_course(self):
        """« Call center » entre dans la prévisualisation, mais l'écriture exigera sa Course."""
        ligne = Ligne(onglet='Call center', mois=[une_case_mois(11, 'NOVEMBRE', 20000)])
        plan = self.plan([ligne], [fiche()], tarifs=dict(TARIFS), appariement_=appariement(
            **{'call center': ('Call center', 'a_creer')}))
        self.assertEqual(len(plan.inscriptions), 1)
        self.assertEqual(plan.groupes[0].titre, 'Call center')
        self.assertEqual([p.montant for p in plan.paiements], [20000])
        signale = [e for e in plan.ecarts if e[0] == 'formation déclarée à créer au catalogue']
        self.assertEqual(len(signale), 1)
        self.assertIn('40 000 FCFA/mois', signale[0][2])

    def test_le_cout_total_du_registre_reste_a_la_saisie_manuelle(self):
        ligne = Ligne(onglet='ANCIENS ETUDIANTS', option='ANGLAIS', cout_total=50000)
        plan = self.plan([ligne], appariement_=appariement(
            **{'anciens etudiants': (None, 'registre')}))
        self.assertEqual(plan.paiements, [])
        signale = [e for e in plan.ecarts if e[0] == 'coût total non importé']
        self.assertEqual(len(signale), 1)
        self.assertIn('50 000 FCFA', signale[0][2])

    def test_une_formation_absente_du_catalogue_est_signalee(self):
        plan = self.plan([Ligne(onglet='Chinois')],
                         appariement_=appariement(**{'chinois': ('Chinois', 'importee')}))
        self.assertEqual(plan.inscriptions, [])
        self.assertEqual(plan.ecartes[0][0], 'formation absente du catalogue')

    def test_un_classeur_trier_par_classeur(self):
        plan = self.plan([Ligne(onglet='Anglais')], classeur='Autre chose.xlsx')
        self.assertEqual(plan.inscriptions, [])

    def test_une_case_de_mois_douteuse_ne_devient_pas_un_paiement(self):
        plan = self.plan([Ligne(mois=[une_case_mois(11, 'NOVEMBRE', None, 'ambigu',
                                                    'MAI-JUIN juil 75000')])])
        self.assertEqual(plan.paiements, [])
        self.assertIn('case de mois non chiffrée', [e[0] for e in plan.ecarts])

    def test_un_groupe_sans_date_se_pose_au_premier_jour_du_mois(self):
        plan = self.plan([Ligne(date_inscription=None, mois=[])])
        self.assertEqual(plan.groupes[0].debut, dt.date(2026, 11, 1))
        self.assertTrue(plan.groupes[0].debut_deduit)
        self.assertIn('aucune date dans l\'onglet', [e[0] for e in plan.ecarts])

    def test_un_groupe_termine_ne_passe_pas_en_cours(self):
        plan = self.plan([Ligne(date_inscription=dt.date(2024, 1, 10), mois=[])])
        self.assertEqual(plan.groupes[0].statut, 'COMPLETED')

    def test_une_inscription_que_le_classeur_dit_finie_passe_en_terminee(self):
        plan = self.plan([Ligne(commentaire='formation terminée', mois=[])])
        self.assertEqual(plan.inscriptions[0].statut, 'COMPLETED')

    def test_le_tarif_vient_du_catalogue_pas_du_classeur(self):
        plan = self.plan([Ligne(mensuel_prevu=35000, mois=[])],
                         tarifs={'Anglais': {'frais': 225000, 'duree': 9, 'mensuel': 25000}})
        self.assertEqual(plan.inscriptions[0].net, 225000)
        self.assertIn('mensualité annoncée hors de la bande', [e[0] for e in plan.ecarts])

    def test_un_trop_percu_se_signale_sans_se_corriger(self):
        inscrit = dt.date(2026, 9, 10)
        # Une case aberrante est conservée telle quelle et signalée ; elle ne
        # devient pas un trop-perçu quand elle reste sous le net du dossier.
        plan = self.plan([Ligne(date_inscription=inscrit,
                                 mois=[une_case_mois(10, 'OCTOBRE', 150000)])],
                         tarifs={'Anglais': {'frais': 225000, 'duree': 9, 'mensuel': 25000}})
        self.assertEqual([p.montant for p in plan.paiements], [150000])
        self.assertNotIn('trop-perçu', [e[0] for e in plan.ecarts])
        self.assertIn('mensualité du Sheet hors de la bande', [e[0] for e in plan.ecarts])
        # Un vrai trop-perçu vient de la somme des mensualités du Sheet.
        plan = self.plan([Ligne(date_inscription=inscrit, mois=[
            une_case_mois(10, 'OCTOBRE', 25000),
            une_case_mois(11, 'NOVEMBRE', 25000),
        ])], tarifs={'Anglais': {'frais': 40000, 'duree': 9, 'mensuel': 25000}})
        self.assertEqual([p.montant for p in plan.paiements], [25000, 25000])
        self.assertIn('trop-perçu', [e[0] for e in plan.ecarts])

    # -- identités --------------------------------------------------------
    def test_un_compte_retrouve_par_son_telephone_ne_se_cree_pas_deux_fois(self):
        existants = [{'id': 'u1', 'email': 'ancien@x.com', 'telephone': '+242 06 78 13 74 0',
                      'nom': 'Louamba', 'prenom': 'Brivah'}]
        plan = self.plan([Ligne()], [fiche(telephone='067813740')], existants=existants)
        self.assertEqual(plan.comptes[0].identifiant, 'u1')
        self.assertEqual(plan.comptes[0].correspondance, 'telephone')
        self.assertEqual(len([c for c in plan.comptes if c.a_creer]), 0)

    def test_l_adresse_d_un_compte_ouvre_gagne_sur_le_rest(self):
        existants = [{'id': 'u1', 'email': 'brivah@test.local', 'telephone': '',
                      'nom': '', 'prenom': ''}]
        plan = self.plan([Ligne()], [fiche()], existants=existants)
        self.assertEqual((plan.comptes[0].identifiant, plan.comptes[0].correspondance),
                         ('u1', 'email'))

    def test_deux_homonymes_ne_partagent_jamais_le_meme_compte(self):
        existants = [{'id': 'u1', 'email': 'un@x.com', 'telephone': '060000000',
                      'nom': 'LOUAMBA', 'prenom': 'Brivah'}]
        plan = self.plan([Ligne(nom='LOUAMBA Brivah'), Ligne(nom='LOUAMBA Brivah', ligne=8)],
                         [fiche(), fiche(prenom='Severdy', email='deux@x.com',
                                         telephone='044094033')], existants=existants)
        rejoins = [c for c in plan.comptes if not c.a_creer]
        self.assertEqual(len(rejoins), 1)

    def test_une_ressemblance_de_nom_ne_suffit_pas_a_rallier_deux_eleves(self):
        """LOUAMBA Brivah et LOUAMBA severdy sont deux personnes : le nom complet decide seul."""
        existants = [{'id': 'u1', 'email': 'un@x.com', 'telephone': '', 'nom': 'LOUAMBA',
                      'prenom': ''}]
        plan = self.plan([Ligne(nom='LOUAMBA Brivah')], existants=existants)
        self.assertIsNone(plan.comptes[0].identifiant)

    def test_un_compte_ne_sert_qu_une_fois(self):
        existants = [{'id': 'u1', 'email': '', 'telephone': '067813740', 'nom': '',
                      'prenom': ''}]
        plan = self.plan([Ligne()], [fiche(telephone='067813740'),
                                     fiche(complet='AUTRE Nom', nom='AUTRE', prenom='Nom',
                                           telephone='067813740', email='autre@x.com')],
                         existants=existants)
        self.assertEqual(len([c for c in plan.comptes if not c.a_creer]), 1)

    def test_un_eleve_d_onglet_sans_fiche_est_signale(self):
        plan = self.plan([Ligne(nom='TEKELE Valencia')], [])
        self.assertIn('élève sans fiche individuelle', [e[0] for e in plan.ecarts])

    def test_deux_lignes_de_fiche_pour_un_meme_eleve_ne_font_qu_un_compte(self):
        plan = self.plan([Ligne()], [fiche(), fiche(ligne=9, telephone='060000000')])
        self.assertEqual(len(plan.comptes), 1)
        self.assertIn('numéros multiples pour un même nom', [e[0] for e in plan.ecarts])

    def test_un_meme_numero_sur_deux_noms_est_signale_sans_fusion(self):
        """Deux orthographes, ou deux enfants d'une même famille : le classeur ne décide pas."""
        plan = self.plan([Ligne(nom='MIALOUKOU Badirila')], [
            fiche(complet='MIAYOUKOU Badirila', nom='MIAYOUKOU Badirila', prenom='Franstell',
                  telephone='066328658', email=''),
            fiche(complet='MIALOUKOU BADIRILA Leslie', nom='MIALOUKOU BADIRILA',
                  prenom='Leslie', telephone='0663 28 65 8', ligne=39, email='')])
        self.assertEqual(len(plan.comptes), 3)
        signale = [e for e in plan.ecarts if e[0] == 'même numéro pour deux fiches']
        self.assertEqual(len(signale), 1)
        self.assertIn('066328658', signale[0][1])


# ---------------------------------------------------------------------------
class ChargeurDeClasseur:
    """Analyseur de fortune : la commande teste ses écritures sans aucun classeur déposé."""

    def __init__(self, source):
        self._source = source

    def collecter(self, dossier):
        self.details = 5
        self.__dict__.update(self._source.__dict__)


class EcritureEnBaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cours = Course.objects.create(title='Anglais', domain='Langues',
                                          duration_months=9, fee_amount=225000)
        # « Caisse principale » est posée par la migration de paramètres ; l'import la retrouve.
        cls.caisse, _creee = CashAccount.objects.get_or_create(name='Caisse principale')
        cls.secretaire = User.objects.create_user(
            email='secretaire@univers.academy', password='x', first_name='Marie',
            last_name='Nguesso', account_status=AccountStatus.ACTIVE)
        for cle in (RoleKey.ETUDIANT, RoleKey.ASSISTANT_ADMIN):
            Role.objects.get_or_create(key=cle, defaults={'label': cle.label})

    def importer(self, lignes, fiches=(), *arguments, appariement_=None):
        analyse = Analyse(lignes=lignes, fiches=fiches,
                          stats=[('Gestion des étudiants.xlsx', l.onglet, 1, 1, [])
                                 for l in lignes],
                          appariement=appariement_ or appariement())
        import core.management.commands.importer_etudiants as commande
        commande.Analyseur = lambda: ChargeurDeClasseur(analyse)
        call_command('importer_etudiants', '--classeur', 'Gestion des étudiants.xlsx',
                     *arguments, stdout=io.StringIO())

    def solde(self):
        return CashAccount.objects.get(pk=self.caisse.pk).balance

    def test_une_formation_declaree_sans_course_bloque_lecriture(self):
        with self.assertRaisesMessage(CommandError, 'Call center'):
            self.importer([Ligne(onglet='Call center',
                                 mois=[une_case_mois(11, 'NOVEMBRE', 20000)])],
                          [fiche()], '--ecrire', appariement_=appariement(
                              **{'call center': ('Call center', 'a_creer')}))
        self.assertEqual(Enrollment.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)

    def test_l_import_cree_comptes_groupes_inscriptions_et_encaissements(self):
        self.importer([Ligne(date_inscription=dt.date(2026, 10, 12),
                             mois=[une_case_mois(11, 'NOVEMBRE', 25000)])],
                      [fiche()], '--ecrire')
        eleve = User.objects.get(email='brivah@test.local')
        self.assertTrue(eleve.has_role(RoleKey.ETUDIANT))
        # Par défaut, un compte étudiant arrive en attente d'approbation.
        self.assertEqual(eleve.account_status, AccountStatus.PENDING_APPROVAL)
        self.assertEqual(CourseSession.objects.filter(course=self.cours).count(), 1)
        dossier = Enrollment.objects.get(student=eleve)
        self.assertEqual(dossier.net_amount, 225000)
        self.assertEqual([p.amount for p in dossier.payments.all()], [25000])
        self.assertFalse(dossier.payments.filter(motif=Payment.Motif.ENROLLMENT).exists())
        self.assertEqual(CashTransaction.objects.filter(
            category__name='Paiements des étudiants').count(), 1)
        self.assertEqual(self.solde(), 25000)

    def test_une_fiche_sans_adresse_recoit_une_adresse_de_repli_a_remplacer(self):
        self.importer([Ligne(nom='TEKELE Valencia')],
                      [fiche(complet='TEKELE Valencia', nom='TEKELE', prenom='Valencia',
                             email='', telephone='')], '--ecrire')
        eleve = User.objects.get(last_name='TEKELE')
        self.assertTrue(eleve.email.endswith(import_eleves.SUFFIXE_SANSDRESSE))

    def test_relancer_la_commande_ne_cree_aucun_doublon(self):
        lignes = [Ligne(date_inscription=dt.date(2026, 10, 12),
                        mois=[une_case_mois(11, 'NOVEMBRE', 25000)])]
        self.importer(lignes, [fiche()], '--ecrire')
        avant = (User.objects.count(), CourseSession.objects.count(), Enrollment.objects.count(),
                 Payment.objects.count(), CashTransaction.objects.count())
        self.importer(lignes, [fiche()], '--ecrire')
        self.assertEqual((User.objects.count(), CourseSession.objects.count(),
                          Enrollment.objects.count(), Payment.objects.count(),
                          CashTransaction.objects.count()), avant)

    def test_une_ligne_deja_posee_par_l_import_ne_se_rejoue_pas(self):
        """La marque de l'import retrouvée en base : l'écriture engagée reste telle quelle."""
        self.importer([Ligne(date_inscription=dt.date(2026, 10, 12),
                             mois=[une_case_mois(11, 'NOVEMBRE', 25000)])],
                      [fiche()], '--ecrire')
        dossier = Enrollment.objects.get()
        self.assertIn(import_eleves.MARQUE, dossier.notes)
        self.importer([Ligne(date_inscription=dt.date(2026, 10, 12),
                             mois=[une_case_mois(11, 'NOVEMBRE', 25000)])],
                      [fiche()], '--ecrire', '--efface')
        self.assertEqual(Enrollment.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(self.solde(), 25000)

    def test_efface_ne_supprime_rien_quand_la_base_vient_de_l_import(self):
        compte = User.objects.create_user(email='brivah@test.local', password='x',
                                          first_name='Brivah', last_name='LOUAMBA',
                                          account_status=AccountStatus.ACTIVE)
        session = CourseSession.objects.create(
            course=self.cours, starts_at=dt.date(2026, 10, 1), ends_at=dt.date(2027, 7, 1),
            schedule='Anglais — import', status='ACTIVE')
        Enrollment.objects.create(student=compte, session=session, net_amount=225000,
                                  notes=f'{import_eleves.MARQUE} — classeur')
        self.importer([Ligne(mois=[])], [fiche()], '--ecrire', '--efface')
        self.assertEqual(Enrollment.objects.count(), 2)

    def test_efface_refuse_de_supprimer_sans_le_dire(self):
        eleve = User.objects.create_user(email='demo@x.com', password='x', first_name='Alice',
                                         last_name='Mabiala')
        session = CourseSession.objects.create(
            course=self.cours, starts_at=dt.date(2026, 10, 12), ends_at=dt.date(2027, 7, 12),
            schedule='Lun-Ven', status='ACTIVE')
        Enrollment.objects.create(student=eleve, session=session, net_amount=225000)
        with self.assertRaises(CommandError) as refuse:
            self.importer([Ligne(mois=[])], [fiche()], '--ecrire')
        self.assertIn('--efface', str(refuse.exception))
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_efface_supprime_inscriptions_et_entrees_de_caisse_sauf_les_sorties(self):
        eleve = User.objects.create_user(email='demo@x.com', password='x', first_name='Alice',
                                         last_name='Mabiala')
        session = CourseSession.objects.create(
            course=self.cours, starts_at=dt.date(2026, 10, 12), ends_at=dt.date(2027, 7, 12),
            schedule='Lun-Ven', status='ACTIVE')
        dossier = Enrollment.objects.create(student=eleve, session=session, net_amount=225000)
        categorie, _cree = TransactionCategory.objects.get_or_create(
            name='Paiements des étudiants', direction=TransactionCategory.Direction.IN)
        sorties, _creee = TransactionCategory.objects.get_or_create(
            name='Salaires', direction=TransactionCategory.Direction.OUT)
        Payment.objects.create(enrollment=dossier, amount=25000, method=Payment.Method.CASH,
                               transaction=CashTransaction.objects.create(
                                   tx_type=CashTransaction.Type.IN, category=categorie,
                                   label='Paiement étudiant', amount=25000, account=self.caisse))
        depart, _cree = TransactionCategory.objects.get_or_create(
            name='Ajustements de solde', direction=TransactionCategory.Direction.IN)
        CashTransaction.objects.create(tx_type=CashTransaction.Type.IN, category=depart,
                                       label='Apport de départ du portefeuille',
                                       amount=175000, account=self.caisse)
        CashTransaction.objects.create(tx_type=CashTransaction.Type.OUT, category=sorties,
                                       label='Ordinateur', amount=200000, account=self.caisse)
        self.importer([Ligne(mois=[])], [fiche()], '--ecrire', '--efface')
        self.assertEqual(Enrollment.objects.count(), 1)  # celle du classeur, pas la démo
        self.assertFalse(Enrollment.objects.filter(student=eleve).exists())
        self.assertEqual(Payment.objects.count(), 0)  # aucun frais importé du classeur
        self.assertEqual(CashTransaction.objects.filter(label='Ordinateur').count(), 1)
        self.assertEqual(CashTransaction.objects.filter(
            category__name='Paiements des étudiants').count(), 0)

    def test_le_compte_retrouve_garde_son_role_et_son_adresse(self):
        existant = User.objects.create_user(email='brivah@test.local', password='motdepasse',
                                            first_name='Brivah', last_name='LOUAMBA',
                                            account_status=AccountStatus.ACTIVE)
        existant.roles.add(Role.objects.get(key=RoleKey.ASSISTANT_ADMIN))
        self.importer([Ligne(mois=[])], [fiche()], '--ecrire')
        existant.refresh_from_db()
        self.assertFalse(existant.has_role(RoleKey.ETUDIANT))
        self.assertTrue(existant.has_role(RoleKey.ASSISTANT_ADMIN))
        # Une approbation déjà accordée ne se défait pas en relançant l'import.
        self.assertEqual(existant.account_status, AccountStatus.ACTIVE)
        self.assertEqual(Enrollment.objects.filter(student=existant).count(), 1)

    def test_les_doublons_se_reconnaissent_par_le_nom_et_les_encaissements(self):
        """Même nom, accent ou casse en moins : seule la caisse tranche le doublon."""
        reel = User.objects.create_user(
            email='noellie@universe.academy', password='x',
            first_name='noéllie', last_name='Etali', account_status=AccountStatus.ACTIVE)
        importe = User.objects.create_user(
            email='noellie-etali-1@sans-adresse.local', password='x',
            first_name='Noellie', last_name='ETALI', account_status=AccountStatus.DISABLED)
        session = CourseSession.objects.create(
            course=self.cours, starts_at=dt.date(2026, 10, 12),
            ends_at=dt.date(2027, 7, 12), schedule='Anglais — doublon', status='ACTIVE')

        dossier_importe = Enrollment.objects.create(
            student=importe, session=session, net_amount=120000)
        Payment.objects.create(enrollment=dossier_importe, amount=30000,
                               method=Payment.Method.CASH,
                               status=Payment.Status.COMPLETED)
        self.assertEqual(doublon_importe(reel), importe)
        self.assertIsNone(doublon_importe(importe))
        self.assertIsNone(compte_reel_a_paiements('noéllie', 'Etali'))

        dossier_reel = Enrollment.objects.create(
            student=reel, session=session, net_amount=180000)
        Payment.objects.create(enrollment=dossier_reel, amount=25000,
                               method=Payment.Method.CASH,
                               status=Payment.Status.COMPLETED)
        self.assertEqual(compte_reel_a_paiements('Noellie', 'ETALI'), reel)

        Payment.objects.all().delete()
        self.assertIsNone(doublon_importe(reel))
        self.assertIsNone(compte_reel_a_paiements('Noellie', 'ETALI'))
