"""La coquille doit suivre la langue choisie, rester neutre côté thème et
empiler ses notifications hors du fil de la page."""

import re
from pathlib import Path

import polib
from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import (
    AccessRequest, CashTransaction, Enrollment, Notification, RoleKey,
)
from core.tests.base import BusinessTestBase


class DureesNotificationsTest(SimpleTestCase):
    """Le popup reste bref et le son s'arrête avec lui, sans secret côté JS."""

    def test_les_durees_demandees_sont_dans_le_script(self):
        source = (Path(settings.BASE_DIR) / 'static' / 'js'
                  / 'notifications.js').read_text(encoding='utf-8')

        self.assertIn('const DUREE_TOAST = 2500;', source)
        self.assertIn('const DUREE_SONNERIE = 3000;', source)
        self.assertNotIn('success: 12000', source)
        self.assertNotIn('DUREE_SONNERIE = 8000', source)


class ContrasteSombreTest(SimpleTestCase):
    """Les utilitaires Tailwind des formulaires restent lisibles la nuit."""

    @staticmethod
    def source_css():
        return (Path(settings.BASE_DIR) / 'static' / 'css'
                / 'input.css').read_text(encoding='utf-8')

    def test_un_bouton_sombre_ne_devient_pas_blanc_sur_blanc(self):
        regle = re.search(
            r'html\[data-theme="dark"\] \.bg-slate-800,\s*'
            r'html\[data-theme="dark"\] \.bg-slate-900 \{[^}]*\}',
            self.source_css(),
        )

        self.assertIsNotNone(regle)
        self.assertIn('var(--ua-surface-3)', regle.group(0))
        self.assertNotIn('var(--ua-ink)', regle.group(0))

    def test_les_options_natives_et_les_textes_suivent_le_theme(self):
        source = self.source_css()

        self.assertIn('html[data-theme="dark"] select option,', source)
        self.assertIn('html[data-theme="dark"] .text-slate-800,', source)
        self.assertIn('html[data-theme="dark"] .divide-slate-200 > * + *',
                      source)

    def test_les_valeurs_tailwind_arbitraires_suivent_le_theme(self):
        source = self.source_css()

        self.assertIn('html[data-theme="dark"] .bg-\\[\\#fbfbff\\]', source)
        self.assertIn('html[data-theme="dark"] .border-\\[\\#e6e7f5\\]',
                      source)

    def test_les_couleurs_en_ligne_claires_sont_remappees(self):
        source = self.source_css()

        self.assertIn('[style*="color:#1e2044"]', source)
        self.assertIn('[style*="border-color:#e6e7f5"]', source)
        self.assertIn('[style*="background:#f7f7fe"]', source)


class BasculeDeLangueTest(BusinessTestBase):
    def test_la_langue_par_defaut_reste_le_francais(self):
        page = self.client_for(self.direction).get(reverse('core:dashboard:dashboard-router'), follow=True)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Déconnexion')
        self.assertNotContains(page, '>Sign out<')

    def test_le_selecteur_de_langue_affiche_les_deux_options(self):
        page = self.client_for(self.direction).get(reverse('core:dashboard:dashboard-router'), follow=True)
        self.assertContains(page, 'name="language" value="fr"')
        self.assertContains(page, 'name="language" value="en"')
        self.assertContains(page, 'action="/i18n/setlang/"')

    def test_changer_de_langue_traduit_la_coquille(self):
        client = self.client_for(self.direction)
        reponse = client.post(
            reverse('set_language'),
            {'language': 'en', 'next': reverse('core:dashboard:dashboard-router')},
        )
        self.assertEqual(reponse.status_code, 302)

        page = client.get(reverse('core:dashboard:dashboard-router'), follow=True)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '<html lang="en"')
        self.assertContains(page, 'Sign out')
        self.assertContains(page, 'Main navigation')
        self.assertNotContains(page, 'Déconnexion')

    def test_le_guichet_de_validation_se_traduit_aussi(self):
        student = self.make_user(RoleKey.ETUDIANT, 'guichet.en@test.local')
        dossier = Enrollment.objects.create(
            student=student,
            session=self.session,
            status=Enrollment.Status.PENDING,
            tariff_amount=self.course.fee_amount,
            discount_amount=0,
            net_amount=self.course.fee_amount,
            registered_by=self.secretaire,
        )
        client = self.client_for(self.direction)
        client.post(reverse('set_language'), {'language': 'en', 'next': '/'})

        page = client.get(reverse('core:dashboard:direction-dashboard'))
        self.assertContains(page, 'Enrollments awaiting validation')
        self.assertContains(page, 'Validate</button>')
        self.assertNotContains(page, 'Inscriptions en attente de validation')
        self.assertEqual(
            Enrollment.objects.get(pk=dossier.pk).status,
            Enrollment.Status.PENDING,
        )


class ThemeSombreTest(BusinessTestBase):
    def test_le_theme_est_resolu_avant_la_peinture(self):
        page = self.client_for(self.direction).get(reverse('core:dashboard:dashboard-router'), follow=True)
        self.assertContains(page, 'data-theme="light"')
        self.assertContains(page, "localStorage.getItem('ua-theme')")

    def test_le_bouton_de_theme_est_present_et_accessible(self):
        page = self.client_for(self.direction).get(reverse('core:dashboard:dashboard-router'), follow=True)
        self.assertContains(page, 'id="ua-theme-btn"')
        self.assertContains(page, 'Changer de thème')

    def test_la_feuille_compilee_porte_le_theme_sombre(self):
        from pathlib import Path
        from django.conf import settings

        css = Path(settings.STATICFILES_DIRS[0]) / 'css' / 'output.css'
        contenu = css.read_text(encoding='utf-8', errors='replace').replace('"', '')
        self.assertIn('data-theme=dark', contenu)
        self.assertIn('--ua-surface', contenu)

    def test_la_feuille_compilee_est_versionnee_pour_le_cache(self):
        page = self.client.get(reverse('core:home'))
        self.assertContains(page, 'css/output.css?v=20261126-theme-mobile')

    def test_le_bouton_de_theme_reste_visible_sur_mobile(self):
        page = self.client_for(self.direction).get(
            reverse('core:dashboard:dashboard-router'), follow=True)
        self.assertContains(page, 'ua-theme-toggle')

        source = (Path(settings.BASE_DIR) / 'static' / 'css'
                  / 'input.css').read_text(encoding='utf-8')
        self.assertIn(
            '    .ua-theme-toggle {\n        display: inline-grid;\n    }',
            source,
        )

        css = (Path(settings.STATICFILES_DIRS[0]) / 'css'
               / 'output.css').read_text(encoding='utf-8', errors='replace')
        self.assertIn('.ua-theme-toggle{display:inline-grid}', css)


# Par défaut, FallbackStorage lit le cookie avant la session et s'arrête dès que
# le cookie est absent : les messages préparés ci-dessous passent donc par le
# magasin de session, seul endroit que la vue acceptera de relire ici.
@override_settings(
    MESSAGE_STORAGE='django.contrib.messages.storage.session.SessionStorage')
class NotificationFlottanteTest(BusinessTestBase):
    """Un message de l'application devient une carte empilée, plus un bloc dans la page."""

    def empiler(self, client, niveau, texte):
        from django.contrib.messages.storage.base import Message
        from django.contrib.messages.storage.cookie import MessageEncoder

        session = client.session
        session['_messages'] = MessageEncoder().encode([Message(niveau, texte, '')])
        session.modified = True
        session.save()

    def page_coquille(self, client):
        return client.get(reverse('core:dashboard:dashboard-router'), follow=True)

    def test_un_message_sempile_en_carte_flottante(self):
        client = self.client_for(self.direction)
        self.empiler(client, 25, 'Paiement enregistré')
        page = self.page_coquille(client)

        self.assertContains(page, 'id="ua-toasts"')
        self.assertContains(page, 'ua-toast--success')
        self.assertContains(page, 'Paiement enregistré')
        self.assertContains(page, 'ua-toast-fermer')
        self.assertContains(page, 'js/notifications.js')

    def test_le_bloc_inline_a_disparu_du_fil_de_la_page(self):
        client = self.client_for(self.direction)
        self.empiler(client, 40, 'Encaissement refusé')
        page = self.page_coquille(client)

        self.assertContains(page, 'ua-toast--error')
        self.assertNotContains(page, 'space-y-2 mb-5')

    def test_le_bouton_de_son_est_dans_la_barre(self):
        page = self.page_coquille(self.client_for(self.direction))
        self.assertContains(page, 'id="ua-son-btn"')
        self.assertContains(page, 'Sons de notification')
        self.assertContains(page, 'data-son="on"')
        self.assertContains(page, "localStorage.getItem('ua-son')")

    def test_la_coquille_de_notification_se_traduit(self):
        client = self.client_for(self.direction)
        client.post(reverse('set_language'), {'language': 'en', 'next': '/'})
        self.empiler(client, 20, 'Dossier déposé')
        page = self.page_coquille(client)

        self.assertContains(page, 'Notification sounds')
        self.assertContains(page, 'Dismiss this notification')


class ClocheRappelTest(BusinessTestBase):
    """Le rappel persistant : c'est le travail qui l'éteint, jamais le temps."""

    def setUp(self):
        self.route = reverse('core:dashboard:dashboard-router')

    def brouillon_de_caisse(self):
        return CashTransaction.objects.create(
            tx_type=CashTransaction.Type.IN,
            category=self.income_category,
            label='Encaissement à valider',
            amount=25000,
            account=self.cash,
            status=CashTransaction.Status.DRAFT,
            occurred_at=timezone.localtime(timezone.now()),
            created_by=self.assistant,
        )

    def notification(self, user):
        return Notification.objects.create(
            user=user,
            title='Compte approuvé',
            message='Votre compte vient d’être activé.',
            notification_type=Notification.Type.ACCOUNT_APPROVED,
        )

    def page(self, user):
        return self.client_for(user).get(self.route, follow=True)

    def test_une_file_non_vide_allume_la_pastille(self):
        self.brouillon_de_caisse()
        page = self.page(self.assistant)

        self.assertContains(page, 'id="ua-cloche"')
        self.assertContains(page, 'class="ua-cloche-pastille">1<')
        self.assertContains(page, 'Écritures de caisse en brouillon')
        self.assertContains(page, reverse('core:dashboard:journal'))

    def test_la_pastille_compte_taches_et_notifications_non_lues(self):
        self.brouillon_de_caisse()
        self.notification(self.assistant)
        page = self.page(self.assistant)

        self.assertContains(page, 'class="ua-cloche-pastille">2<')
        self.assertContains(page, 'Compte approuvé')

    def test_la_file_vide_etaint_la_pastille(self):
        page = self.page(self.etudiant)

        self.assertContains(page, 'id="ua-cloche"')
        self.assertNotContains(page, 'ua-cloche-pastille')
        self.assertContains(page, 'Rien à traiter')

    def test_marquer_lues_eteint_le_rappel(self):
        note = self.notification(self.etudiant)
        client = self.client_for(self.etudiant)

        self.assertContains(client.get(self.route, follow=True), 'ua-cloche-pastille')
        self.assertEqual(client.get(reverse('core:dashboard:notifications-lire')).status_code, 405)

        reponse = client.post(reverse('core:dashboard:notifications-lire'))
        self.assertEqual(reponse.status_code, 302)
        note.refresh_from_db()
        self.assertTrue(note.is_read)
        self.assertNotContains(client.get(self.route, follow=True), 'ua-cloche-pastille')

    def test_le_rappel_ne_pointe_jamais_une_porte_fermee(self):
        AccessRequest.objects.create(
            user=self.etudiant, requested_role=RoleKey.FORMATEUR)
        self.brouillon_de_caisse()

        client = self.client_for(self.super_admin)
        page = client.get(self.route, follow=True)
        self.assertContains(page, 'class="ua-cloche-pastille">2<')
        self.assertContains(page, reverse('core:dashboard:access-requests'))
        for url in (reverse('core:dashboard:access-requests'),
                    reverse('core:dashboard:journal')):
            self.assertEqual(client.get(url).status_code, 200, url)

    def test_le_panneau_de_rappel_se_traduit(self):
        self.brouillon_de_caisse()
        client = self.client_for(self.assistant)
        client.post(reverse('set_language'), {'language': 'en', 'next': '/'})
        page = client.get(self.route, follow=True)

        self.assertContains(page, 'Draft cash entries to post')
        self.assertContains(page, 'To process')

    def test_le_sondage_detecte_les_demandes_accessibles_en_temps_reel(self):
        client = self.client_for(self.assistant)
        page = client.get(self.route, follow=True)
        self.assertContains(page, 'data-poll-url')
        url = reverse('core:dashboard:notifications-poll')
        avant = client.get(url).json()['event_cursor']

        AccessRequest.objects.create(
            user=self.etudiant, requested_role=RoleKey.ETUDIANT,
        )

        reponse = client.get(url)
        self.assertEqual(reponse.status_code, 200)
        etat = reponse.json()
        self.assertNotEqual(etat['event_cursor'], avant)
        self.assertEqual(etat['total'], 1)
        self.assertEqual(etat['tasks'][0]['count'], 1)
        self.assertEqual(
            etat['tasks'][0]['url'],
            reverse('core:dashboard:access-requests'),
        )

    def test_une_demande_declenche_le_sondage_sur_tous_les_dashboards(self):
        client = self.client_for(self.assistant)
        url = reverse('core:dashboard:notifications-poll')
        avant = client.get(url).json()['event_cursor']

        AccessRequest.objects.create(
            user=self.etudiant, requested_role=RoleKey.FORMATEUR,
        )

        etat = client.get(url).json()
        self.assertNotEqual(etat['event_cursor'], avant)
        self.assertEqual(etat['total'], 0)

    def test_une_notification_declenche_le_sondage_sur_tous_les_dashboards(self):
        client = self.client_for(self.assistant)
        url = reverse('core:dashboard:notifications-poll')
        avant = client.get(url).json()['event_cursor']

        self.notification(self.etudiant)

        etat = client.get(url).json()
        self.assertNotEqual(etat['event_cursor'], avant)
        self.assertEqual(etat['total'], 0)

    def test_le_sondage_renvoie_seulement_les_notifications_du_compte(self):
        self.notification(self.assistant)
        self.notification(self.etudiant)

        etat = self.client_for(self.assistant).get(
            reverse('core:dashboard:notifications-poll'),
        ).json()

        self.assertEqual(len(etat['notifications']), 1)
        self.assertEqual(etat['notifications'][0]['title'], 'Compte approuvé')
        self.assertEqual(etat['notifications'][0]['message'],
                         'Votre compte vient d’être activé.')

    def test_le_sondage_oublie_les_notifications_deja_lues(self):
        note = self.notification(self.etudiant)
        client = self.client_for(self.etudiant)
        url = reverse('core:dashboard:notifications-poll')

        avant = client.get(url).json()
        self.assertEqual(avant['notification_cursor'], str(note.pk))
        self.assertEqual(len(avant['notifications']), 1)

        Notification.objects.filter(pk=note.pk).update(is_read=True)
        apres = client.get(url).json()

        self.assertEqual(apres['notification_cursor'], '')
        self.assertEqual(apres['notifications'], [])
        self.assertEqual(apres['total'], 0)

    def test_le_curseur_du_popup_ignore_les_notifications_dautrui(self):
        self.notification(self.assistant)
        client = self.client_for(self.etudiant)
        url = reverse('core:dashboard:notifications-poll')

        etat = client.get(url).json()

        self.assertEqual(etat['notification_cursor'], '')
        self.assertEqual(etat['notifications'], [])

    def test_la_cloche_initialise_le_curseur_du_popup(self):
        note = self.notification(self.etudiant)
        self.assertContains(
            self.page(self.etudiant),
            'data-notification-cursor="%s"' % note.pk,
        )

    def test_le_sondage_est_reserve_aux_comptes_actifs(self):
        reponse = self.client.get(
            reverse('core:dashboard:notifications-poll'),
        )
        self.assertEqual(reponse.status_code, 302)


class CatalogueAnglaisTest(SimpleTestCase):
    """Une traduction ne peut pas renommer les variables d'un msgid."""

    def test_les_placeholders_sont_identiques(self):
        chemin = (Path(settings.LOCALE_PATHS[0]) / 'en' / 'LC_MESSAGES'
                  / 'django.po')
        catalogue = polib.pofile(str(chemin))
        motif = re.compile(r'%\((\w+)\)([a-z])')
        for entree in catalogue:
            avec = motif.findall(entree.msgid)
            if not avec:
                continue
            with self.subTest(msgid=entree.msgid):
                self.assertCountEqual(avec, motif.findall(entree.msgstr))
