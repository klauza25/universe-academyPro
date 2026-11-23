"""Messagerie interne 1:1 : paires uniques, accès privé, audit et notifications.

Les tests tournent sur la base de test Django : aucune donnée de production
n'est lue ni écrite.
"""
import json

from django.urls import reverse

from core.models import (
    AccountStatus, AuditLog, Conversation, Message, Notification, User,
)
from core.tests.base import BusinessTestBase, TEST_PASSWORD


class MessagerieTest(BusinessTestBase):
    def setUp(self):
        self.liste_url = reverse('core:dashboard:messagerie')
        self.start_url = reverse('core:dashboard:messagerie-start')

    def detail_url(self, conversation):
        return reverse(
            'core:dashboard:messagerie-detail',
            args=[conversation.id],
        )

    def send_url(self, conversation):
        return reverse(
            'core:dashboard:messagerie-send',
            args=[conversation.id],
        )

    def poll_url(self, conversation):
        return reverse(
            'core:dashboard:messagerie-poll',
            args=[conversation.id],
        )

    def ouvre(self, expediteur, destinataire):
        """Ouvre un fil via l'interface, comme un utilisateur le ferait."""
        client = self.client_for(expediteur)
        response = client.post(
            self.start_url, {'destinataire_id': str(destinataire.pk)}
        )
        self.assertEqual(response.status_code, 302)
        return client, Conversation.objects.get()

    # ------------------------------------------------------------------
    # Liste et ouverture
    # ------------------------------------------------------------------

    def test_liste_affiche_les_fils_et_la_recherche(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        Message.objects.create(
            conversation=conversation, sender=self.formateur, body='Bonjour !'
        )

        response = self.client_for(self.etudiant).get(self.liste_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.formateur.display_label)
        self.assertContains(response, 'Bonjour !')

        response = self.client_for(self.etudiant).get(
            self.liste_url, {'q': 'formateur@test.local'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.formateur.display_label)

    def test_ouverture_cree_un_seul_fil_par_paire(self):
        client, conversation = self.ouvre(self.etudiant, self.formateur)
        self.assertEqual(conversation.participants.count(), 2)

        response = client.post(
            self.start_url, {'destinataire_id': str(self.formateur.pk)}
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertEqual(response.url, self.detail_url(conversation))

    def test_ordre_inverse_retrouve_le_meme_fil(self):
        _, conversation = self.ouvre(self.etudiant, self.formateur)

        self.client_for(self.formateur).post(
            self.start_url, {'destinataire_id': str(self.etudiant.pk)}
        )

        self.assertEqual(Conversation.objects.count(), 1)
        self.assertEqual(conversation, Conversation.objects.get())

    def test_ouverture_auditée(self):
        self.ouvre(self.etudiant, self.formateur)

        journal = AuditLog.objects.filter(
            action='MESSAGE_CONVERSATION_OPEN'
        )
        self.assertEqual(journal.count(), 1)
        self.assertEqual(journal.first().actor, self.etudiant)

    def test_impossible_de_secrire_a_soi_meme(self):
        response = self.client_for(self.etudiant).post(
            self.start_url, {'destinataire_id': str(self.etudiant.pk)}
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Conversation.objects.count(), 0)

    def test_destinataire_inactif_ou_invalide_refuse(self):
        inactif = User.objects.create_user(
            email='inactif@test.local', password=TEST_PASSWORD,
            account_status=AccountStatus.DISABLED,
        )
        client = self.client_for(self.etudiant)

        for valeur in (str(inactif.pk), 'pas-un-uuid'):
            with self.subTest(destinataire=valeur):
                response = client.post(
                    self.start_url, {'destinataire_id': valeur}
                )
                self.assertEqual(response.status_code, 404)
        self.assertEqual(Conversation.objects.count(), 0)

    # ------------------------------------------------------------------
    # Accès au fil
    # ------------------------------------------------------------------

    def test_fil_reserve_aux_participants(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)

        self.assertEqual(
            self.client_for(self.etudiant).get(self.detail_url(conversation)).status_code,
            200,
        )
        self.assertEqual(
            self.client_for(self.admin).get(self.detail_url(conversation)).status_code,
            404,
        )

    def test_ouverture_marque_les_messages_recus_comme_lus(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        recu = Message.objects.create(
            conversation=conversation, sender=self.formateur, body='À lire'
        )
        envoye = Message.objects.create(
            conversation=conversation, sender=self.etudiant, body='Déjà mien'
        )
        Notification.objects.create(
            user=self.etudiant,
            title='Nouveau message',
            message='À lire',
            link=self.detail_url(conversation),
            notification_type=Notification.Type.GENERAL,
        )

        self.client_for(self.etudiant).get(self.detail_url(conversation))

        recu.refresh_from_db()
        envoye.refresh_from_db()
        self.assertIsNotNone(recu.read_at)
        self.assertIsNone(envoye.read_at)
        self.assertFalse(Notification.objects.filter(is_read=False).exists())

    def test_ouverture_eteint_uniquement_la_notification_du_fil(self):
        _, conversation = self.ouvre(self.formateur, self.etudiant)
        self.client_for(self.formateur).post(
            self.send_url(conversation), {'body': 'Pour l’étudiant'}
        )
        autre, _ = Conversation.pour(self.admin, self.secretaire)
        Notification.objects.create(
            user=self.etudiant,
            title='Autre avis',
            message='À conserver',
            link=self.detail_url(autre),
            notification_type=Notification.Type.GENERAL,
        )

        self.client_for(self.etudiant).get(self.detail_url(conversation))

        note_fil = Notification.objects.get(link=self.detail_url(conversation))
        note_autre = Notification.objects.get(link=self.detail_url(autre))
        self.assertTrue(note_fil.is_read)
        self.assertFalse(note_autre.is_read)

    def test_poll_des_notifications_expose_le_lien_du_fil(self):
        _, conversation = self.ouvre(self.formateur, self.etudiant)
        self.client_for(self.formateur).post(
            self.send_url(conversation), {'body': 'Regarde ce fil'}
        )

        response = self.client_for(self.etudiant).get(
            reverse('core:dashboard:notifications-poll')
        )

        self.assertEqual(response.status_code, 200)
        notes = json.loads(response.content)['notifications']
        self.assertTrue(
            any(note['link'] == self.detail_url(conversation) for note in notes)
        )

    # ------------------------------------------------------------------
    # Envoi
    # ------------------------------------------------------------------

    def test_envoi_cree_message_notification_et_audit(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        avant = conversation.updated_at

        response = self.client_for(self.etudiant).post(
            self.send_url(conversation), {'body': '  Bonjour formateur  '}
        )

        self.assertEqual(response.status_code, 302)
        message = Message.objects.get()
        self.assertEqual(message.body, 'Bonjour formateur')
        self.assertEqual(message.sender, self.etudiant)
        conversation.refresh_from_db()
        self.assertGreater(conversation.updated_at, avant)

        notification = Notification.objects.get()
        self.assertEqual(notification.user, self.formateur)
        self.assertEqual(notification.notification_type, Notification.Type.GENERAL)
        self.assertEqual(notification.link, self.detail_url(conversation))
        self.assertIn('Bonjour formateur', notification.message)

        journal = AuditLog.objects.get(action='MESSAGE_SEND')
        self.assertEqual(journal.actor, self.etudiant)
        self.assertEqual(journal.after_summary['to'], str(self.formateur.pk))

    def test_envoi_vide_ou_trop_long_refuse(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        client = self.client_for(self.etudiant)

        for corps in ('', '   ', 'x' * 5001):
            with self.subTest(longueur=len(corps)):
                response = client.post(
                    self.send_url(conversation), {'body': corps}
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(Message.objects.count(), 0)
                self.assertEqual(Notification.objects.count(), 0)
                self.assertEqual(
                    AuditLog.objects.filter(action='MESSAGE_SEND').count(), 0
                )

    def test_envoi_par_un_etranger_refuse(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)

        response = self.client_for(self.admin).post(
            self.send_url(conversation), {'body': 'Intrus'}
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Message.objects.count(), 0)

    def test_compteur_de_messages_non_lus(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        Message.objects.create(
            conversation=conversation, sender=self.formateur, body='Non lu'
        )

        response = self.client_for(self.etudiant).get(self.liste_url)

        self.assertEqual(response.context['unread_messages'], 1)
        self.assertContains(response, 'ua-compte-badge')

    # ------------------------------------------------------------------
    # Sondage JSON
    # ------------------------------------------------------------------

    def test_poll_retourne_le_fil_sans_donnee_dautrui(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        Message.objects.create(
            conversation=conversation, sender=self.formateur, body='Message A'
        )
        Message.objects.create(
            conversation=conversation, sender=self.etudiant, body='Message B'
        )
        autre, _ = Conversation.pour(self.admin, self.secretaire)
        Message.objects.create(
            conversation=autre, sender=self.admin, body='Secret'
        )

        response = self.client_for(self.etudiant).get(self.poll_url(conversation))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        donnees = json.loads(response.content)
        self.assertEqual(len(donnees['messages']), 2)
        self.assertEqual(donnees['messages'][0]['corps'], 'Message A')
        self.assertTrue(donnees['messages'][0]['mien'] is False)
        self.assertTrue(donnees['messages'][1]['mien'])
        self.assertTrue(donnees['signature'])
        self.assertNotIn('Secret', response.content.decode())

    def test_poll_reserve_aux_participants(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)

        response = self.client_for(self.admin).get(self.poll_url(conversation))

        self.assertEqual(response.status_code, 404)

    def test_poll_refuse_le_post(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)

        response = self.client_for(self.etudiant).post(
            self.poll_url(conversation)
        )

        self.assertEqual(response.status_code, 405)
