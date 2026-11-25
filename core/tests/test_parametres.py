"""Tests des paramètres généraux : une seule ligne règle toute la plateforme."""
from io import BytesIO

from django.contrib import admin
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from PIL import Image

from core import caisse, parametres
from core.forms import PlatformSettingForm
from core.models import (
    Attendance, CashAccount, CashTransaction, Certificate, Enrollment, Expense,
    Payment, PlatformSetting,
)

from .base import BusinessTestBase


class ParametresGenerauxBase(BusinessTestBase):
    """La ligne de réglages posée par la migration, telle qu'elle naît."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.reglages = PlatformSetting.objects.get()

    def payload(self, **surcharge):
        data = {
            'nom': 'Universe Academy',
            'signature': self.reglages.signature,
            'adresse': self.reglages.adresse,
            'telephone': self.reglages.telephone,
            'email': self.reglages.email,
            'rccm': self.reglages.rccm,
            'niu': self.reglages.niu,
            'cnss': self.reglages.cnss,
            'devise': 'FCFA',
            'seuil_alerte': '80',
        }
        data.update(surcharge)
        return data


def image_upload(nom='image.png', couleur=(40, 90, 160)):
    tampon = BytesIO()
    Image.new('RGB', (8, 8), couleur).save(tampon, format='PNG')
    return SimpleUploadedFile(nom, tampon.getvalue(), content_type='image/png')


class ParametresIdentiteVisuelleTest(ParametresGenerauxBase):
    """Favicon et logo se posent à l'écran et se lisent partout, sans /media/."""

    def setUp(self):
        self.client = self.client_for(self.direction)

    def test_les_images_sont_enregistrees_et_tracees(self):
        page = self.client.post(
            reverse('core:dashboard:platform-settings'),
            self.payload(favicon=image_upload('onglet.png'),
                         logo=image_upload('enseigne.png')))
        self.assertEqual(page.status_code, 302)
        self.reglages.refresh_from_db()
        self.assertTrue(self.reglages.favicon.name.startswith('branding/favicon-'))
        self.assertTrue(self.reglages.logo.name.startswith('branding/logo-'))
        entree = self.assert_audited('PLATFORM_SETTINGS_EDIT', self.reglages.pk)
        self.assertEqual(entree.after_summary['favicon'], self.reglages.favicon.name)
        self.assertEqual(entree.after_summary['logo'], self.reglages.logo.name)

    def test_les_images_sont_servies_sans_exposer_media(self):
        self.client.post(
            reverse('core:dashboard:platform-settings'),
            self.payload(favicon=image_upload('onglet.png'),
                         logo=image_upload('enseigne.png')))
        self.reglages.refresh_from_db()
        accueil = Client().get(reverse('core:home'))
        self.assertContains(accueil, f'href="{self.reglages.favicon_url()}"')
        self.assertContains(accueil, self.reglages.logo_url())

        fichier = self.client.get(self.reglages.logo_url())
        self.assertEqual(fichier.status_code, 200)
        self.assertEqual(fichier['Content-Type'], 'image/png')
        self.assertTrue(b''.join(fichier.streaming_content).startswith(b'\x89PNG'))
        self.assertEqual(self.client.get('/branding/../private/secret.png').status_code, 404)

    def test_une_mauvaise_extension_est_refusee(self):
        forme = PlatformSettingForm(
            instance=self.reglages, data=self.payload(),
            files={'logo': SimpleUploadedFile('logo.txt', b'pas une image',
                                              content_type='text/plain')})
        self.assertFalse(forme.is_valid())
        self.assertIn('logo', forme.errors)

    def test_une_image_trop_lourde_est_refusee(self):
        brut = image_upload('logo.png')
        gros = SimpleUploadedFile('logo.png', brut.read() + b'0' * (2 * 1024 * 1024),
                                  content_type='image/png')
        forme = PlatformSettingForm(
            instance=self.reglages, data=self.payload(), files={'logo': gros})
        self.assertFalse(forme.is_valid())
        self.assertIn('logo', forme.errors)

    def test_effacer_les_images_revient_aux_visuels_d_origine(self):
        self.client.post(
            reverse('core:dashboard:platform-settings'),
            self.payload(favicon=image_upload('onglet.png'),
                         logo=image_upload('enseigne.png')))
        self.reglages.refresh_from_db()
        anciens = (self.reglages.favicon.name, self.reglages.logo.name)

        data = self.payload()
        data.update({'favicon-clear': 'on', 'logo-clear': 'on'})
        self.assertEqual(self.client.post(
            reverse('core:dashboard:platform-settings'), data).status_code, 302)
        self.reglages.refresh_from_db()
        self.assertFalse(self.reglages.favicon)
        self.assertFalse(self.reglages.logo)
        self.assertEqual(self.reglages.favicon_url(), '/static/img/favicon.svg')
        self.assertEqual(self.reglages.logo_url(), '/static/img/logo-univers.jpg')
        self.assertFalse(default_storage.exists(anciens[0]))
        self.assertFalse(default_storage.exists(anciens[1]))

    def test_remplacer_une_image_supprime_l_ancienne(self):
        self.client.post(
            reverse('core:dashboard:platform-settings'),
            self.payload(logo=image_upload('premier.png', (10, 20, 30))))
        self.reglages.refresh_from_db()
        premier = self.reglages.logo.name

        self.client.post(
            reverse('core:dashboard:platform-settings'),
            self.payload(logo=image_upload('second.png', (210, 40, 60))))
        self.reglages.refresh_from_db()
        self.assertNotEqual(self.reglages.logo.name, premier)
        self.assertFalse(default_storage.exists(premier))


class ParametresModeleTest(ParametresGenerauxBase):
    def test_la_ligne_nait_avec_la_migration(self):
        self.assertEqual(PlatformSetting.objects.count(), 1)
        self.assertEqual(self.reglages.nom, 'Universe Academy')
        self.assertEqual(self.reglages.devise, 'FCFA')
        self.assertEqual(self.reglages.seuil_alerte, 80)

    def test_une_seule_ligne_tient_les_reglages_en_base(self):
        """La contrainte tient même contre un script qui forcerait une seconde ligne."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PlatformSetting.objects.create(id=2)

    def test_le_service_ne_cre_jamais_la_ligne(self):
        PlatformSetting.objects.all().delete()
        self.assertEqual(PlatformSetting.objects.count(), 0)
        ligne = parametres.ligne()
        self.assertIsNone(ligne.pk)
        self.assertEqual(ligne.nom, 'Universe Academy')
        self.assertEqual(PlatformSetting.objects.count(), 0)

    def test_le_bloc_legal_ne_sort_que_ce_qu_on_lui_donne(self):
        self.reglages.cnss = ''
        self.reglages.save()
        bloc = parametres.ligne().bloc_legal()
        self.assertEqual(len(bloc), 2)
        self.assertTrue(all(ligne.startswith(('RCCM', 'NIU')) for ligne in bloc))

    def test_un_nom_vide_est_refuse_par_le_formulaire(self):
        forme = PlatformSettingForm(instance=self.reglages, data=self.payload(nom='   '))
        self.assertFalse(forme.is_valid())
        self.assertIn('nom', forme.errors)


class ParametresSeuilTest(ParametresGenerauxBase):
    def test_le_seuil_hors_bornes_est_refuse(self):
        for valeur in ('0', '101', 'abc'):
            forme = PlatformSettingForm(instance=self.reglages,
                                        data=self.payload(seuil_alerte=valeur))
            self.assertFalse(forme.is_valid(), valeur)
            self.assertIn('seuil_alerte', forme.errors)

    def test_la_garde_de_caisse_lit_le_seuil_pose(self):
        """Même écriture, deux seuils : l'avertissement suit le réglage."""
        self.reglages.seuil_alerte = 50
        self.reglages.save()
        CashTransaction.objects.create(
            tx_type=CashTransaction.Type.IN,
            label='Recette de test', amount=100000, account=self.cash,
            status=CashTransaction.Status.VALIDATED,
            category=self.income_category,
        )
        alerte = caisse.avertissement(self.cash, sortie=60000)
        self.assertIn('60 %', alerte)

        self.reglages.seuil_alerte = 90
        self.reglages.save()
        self.assertIsNone(caisse.avertissement(self.cash, sortie=60000))

    def test_l_alerte_nomme_la_devise_reglee(self):
        self.reglages.devise = 'USD'
        self.reglages.save()
        self.cash.currency = 'FCFA'
        self.cash.save(update_fields=['currency'])
        CashTransaction.objects.create(
            tx_type=CashTransaction.Type.IN,
            label='Recette de test', amount=100000, account=self.cash,
            status=CashTransaction.Status.VALIDATED,
            category=self.income_category,
        )
        alerte = caisse.avertissement(self.cash, sortie=90000)
        self.assertIn('USD', alerte)


class ParametresEcranTest(ParametresGenerauxBase):
    def setUp(self):
        self.client = self.client_for(self.direction)

    def test_la_direction_consulte_ses_reglages(self):
        page = self.client.get(reverse('core:dashboard:platform-settings'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Universe Academy')
        self.assertContains(page, self.reglages.telephone)

    def test_la_direction_enregistre_et_sa_trace_rest(self):
        page = self.client.post(
            reverse('core:dashboard:platform-settings'),
            {'nom': 'Académie Univers', 'signature': 'Nouvelle signature',
             'adresse': 'Nouvelle adresse', 'telephone': '+242-09-00-00-00',
             'email': 'nouvel@exemple.local', 'rccm': 'RCCM-NOUVEAU',
             'niu': 'NIU-NOUVEAU', 'cnss': 'CNSS-NOUVEAU',
             'devise': 'FCFA', 'seuil_alerte': '75'})
        self.assertRedirects(
            page, reverse('core:dashboard:platform-settings'),
            fetch_redirect_response=False)
        self.reglages.refresh_from_db()
        self.assertEqual(self.reglages.nom, 'Académie Univers')
        self.assertEqual(self.reglages.seuil_alerte, 75)
        entree = self.assert_audited('PLATFORM_SETTINGS_EDIT', self.reglages.pk)
        self.assertEqual(entree.before_summary['nom'], 'Universe Academy')
        self.assertEqual(entree.after_summary['nom'], 'Académie Univers')

    def test_un_seuil_absurde_est_refuse_sans_rien_ecrire(self):
        page = self.client.post(
            reverse('core:dashboard:platform-settings'),
            {'nom': 'Universe Academy', 'signature': '', 'adresse': '',
             'telephone': '', 'email': '', 'rccm': '', 'niu': '', 'cnss': '',
             'devise': 'FCFA', 'seuil_alerte': '200'})
        self.assertEqual(page.status_code, 200)
        self.reglages.refresh_from_db()
        self.assertEqual(self.reglages.seuil_alerte, 80)

    def test_l_ecran_est_autorise_a_l_assistant_administratif(self):
        client = self.client_for(self.secretaire)
        self.assertEqual(
            client.get(reverse('core:dashboard:platform-settings')).status_code, 200)
        self.assertEqual(
            client.post(reverse('core:dashboard:platform-settings'),
                        {'nom': 'X', 'devise': 'FCFA', 'seuil_alerte': '80'}).status_code,
            302)

    def test_l_historique_des_reglages_parait_sous_le_formulaire(self):
        self.client.post(
            reverse('core:dashboard:platform-settings'),
            {'nom': 'Académie Univers', 'signature': '', 'adresse': '',
             'telephone': '', 'email': '', 'rccm': '', 'niu': '', 'cnss': '',
             'devise': 'FCFA', 'seuil_alerte': '80'})
        page = self.client.get(reverse('core:dashboard:platform-settings'))
        self.assertContains(page, 'PLATFORM_SETTINGS_EDIT')


class ParametresAffichageTest(ParametresGenerauxBase):
    """Ce que la direction écrit dans les réglages se relit sur les écrans."""

    def test_le_nom_de_l_etablissement_signe_le_tableau_de_bord(self):
        self.reglages.nom = 'Centre Univers Academy'
        self.reglages.save()
        page = self.client_for(self.super_admin).get(
            reverse('core:dashboard:super-admin-dashboard'))
        self.assertContains(page, 'Centre Univers Academy')

    def test_le_nom_et_la_devise_sont_passes_aux_gabarits(self):
        self.reglages.devise = 'CDF'
        self.reglages.save()
        page = self.client_for(self.assistant).get(
            reverse('core:dashboard:journal'))
        self.assertContains(page, '<meta name="devise" content="CDF">')
        self.assertContains(page, 'CDF')

    def test_les_coordonnees_imprimees_suivent_le_reglage(self):
        self.reglages.adresse = 'Immeuble Neuve, Avenue Test — Brazzaville'
        self.reglages.telephone = '+242-05-11-22-33'
        self.reglages.email = 'contact@exemple.local'
        self.reglages.rccm = 'CG-BZV-TEST'
        self.reglages.save()
        page = Client().get(reverse('core:home'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Immeuble Neuve, Avenue Test — Brazzaville')
        self.assertContains(page, '+242-05-11-22-33')
        self.assertContains(page, 'contact@exemple.local')

    def test_le_recu_porte_le_nom_et_le_bloc_legal(self):
        self.reglages.nom = 'Académie Univers'
        self.reglages.rccm = 'CG-BZV-01-TEST'
        self.reglages.save()
        client = self.client_for(self.assistant)
        client.post(
            reverse('core:dashboard:payment-create'),
            {'student': self.etudiant.pk, 'enrollment': self.enrollment.pk,
             'amount': '20000', 'method': Payment.Method.CASH,
             'account': self.cash.pk, 'motif': Payment.Motif.MONTHLY,
             'period_year': str(self.today.year),
             'period_month': str(self.today.month),
             'paid_at': self.local_datetime(), 'note': '',
             'submission_key': 'receipt-settings-payment'})
        payment = Payment.objects.get()
        page = client.get(reverse('core:dashboard:payment-receipt', args=[payment.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Académie Univers')
        self.assertContains(page, 'CG-BZV-01-TEST')
        self.assertContains(page, self.reglages.telephone)


class ParametresAdminTest(ParametresGenerauxBase):
    """L'administration Django ne se substitue pas aux écrans validés."""

    TABLES_FERMEES = [Payment, Enrollment, Attendance, Expense, Certificate,
                      PlatformSetting]

    def test_les_tables_financieres_ne_s_edite_pas_dans_django_admin(self):
        for modele in self.TABLES_FERMEES:
            with self.subTest(modele=modele.__name__):
                enregistre = admin.site._registry[modele]
                self.assertFalse(enregistre.has_add_permission(None))
                self.assertFalse(enregistre.has_change_permission(None))
                self.assertFalse(enregistre.has_delete_permission(None))

    def test_toutes_les_tables_financieres_sont_en_consultation_seule(self):
        """Le même contrat vaut pour l'écriture des caisses, lues mais non touchées.

        `ConsultationSeule` ne ferme qu'ajouter, modifier et supprimer : la
        consultation reste celle que Django accorde à qui a le droit d'entrée.
        """
        from core.admin import ConsultationSeule
        for modele in self.TABLES_FERMEES + [CashTransaction, CashAccount]:
            with self.subTest(modele=modele.__name__):
                self.assertIsInstance(
                    admin.site._registry[modele], ConsultationSeule)
