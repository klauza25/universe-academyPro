"""Messagerie interne 1:1 : paires uniques, accès privé, audit et notifications.

Les tests tournent sur la base de test Django : aucune donnée de production
n'est lue ni écrite.
"""
import json

from django.urls import reverse
from django.utils import timezone

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

    def delete_url(self, conversation, message):
        return reverse(
            'core:dashboard:messagerie-delete',
            args=[conversation.id, message.id],
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

    def test_fil_affiche_le_destinataire_dans_la_carte(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)

        response = self.client_for(self.etudiant).get(
            self.detail_url(conversation)
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ua-chat-entete')
        self.assertContains(response, self.formateur.display_label)
        self.assertContains(response, 'Conversation privée')

    def test_messages_recus_et_envoyes_sont_dans_le_meme_fil(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        Message.objects.create(
            conversation=conversation, sender=self.formateur, body='Recu',
        )
        Message.objects.create(
            conversation=conversation, sender=self.etudiant, body='Envoye',
        )

        html = self.client_for(self.etudiant).get(
            self.detail_url(conversation)
        ).content.decode()
        debut = html.index('id="ua-chat-fil"')
        fin = html.index('id="ua-chat-form"')
        segment = html[debut:fin]

        self.assertIn('Recu', segment)
        self.assertIn('Envoye', segment)
        self.assertIn('ua-chat-bulle ', segment)
        self.assertIn('ua-chat-bulle mien', segment)

    def test_fil_affiche_lannee_et_laccuse_de_lecture(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        message = Message.objects.create(
            conversation=conversation, sender=self.etudiant, body='Daté',
            read_at=timezone.now(),
        )

        response = self.client_for(self.etudiant).get(
            self.detail_url(conversation)
        )

        horodatage = timezone.localtime(
            message.created_at
        ).strftime('%d/%m/%Y %H:%M')
        self.assertContains(response, horodatage)
        self.assertContains(response, '· Lu')

    def test_message_non_lu_affiche_envoye(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        Message.objects.create(
            conversation=conversation, sender=self.etudiant, body='En attente',
        )

        response = self.client_for(self.etudiant).get(
            self.detail_url(conversation)
        )

        self.assertContains(response, '· Envoyé')

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
    # Suppression
    # ------------------------------------------------------------------

    def test_expediteur_supprime_son_message_avec_audit(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        message = Message.objects.create(
            conversation=conversation, sender=self.etudiant,
            body='À effacer',
        )

        response = self.client_for(self.etudiant).post(
            self.delete_url(conversation, message)
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.detail_url(conversation))
        self.assertFalse(Message.objects.filter(pk=message.pk).exists())
        journal = AuditLog.objects.get(action='MESSAGE_DELETE')
        self.assertEqual(journal.actor, self.etudiant)
        self.assertEqual(journal.before_summary['length'], len('À effacer'))
        self.assertEqual(journal.entity_id, str(message.id))

    def test_destinataire_ne_peut_pas_supprimer_un_message_recu(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        message = Message.objects.create(
            conversation=conversation, sender=self.etudiant,
            body='Texte protege',
        )

        response = self.client_for(self.formateur).post(
            self.delete_url(conversation, message)
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Message.objects.filter(pk=message.pk).exists())
        self.assertFalse(AuditLog.objects.filter(action='MESSAGE_DELETE').exists())

    def test_etranger_ne_peut_pas_supprimer_un_message(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        message = Message.objects.create(
            conversation=conversation, sender=self.etudiant, body='Prive',
        )

        response = self.client_for(self.admin).post(
            self.delete_url(conversation, message)
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Message.objects.filter(pk=message.pk).exists())

    def test_suppression_refuse_le_get(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        message = Message.objects.create(
            conversation=conversation, sender=self.etudiant, body='Prive',
        )

        response = self.client_for(self.etudiant).get(
            self.delete_url(conversation, message)
        )

        self.assertEqual(response.status_code, 405)
        self.assertTrue(Message.objects.filter(pk=message.pk).exists())

    def test_suppression_demande_confirmation_dans_le_gabarit(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        Message.objects.create(
            conversation=conversation, sender=self.etudiant,
            body='Confirmation',
        )

        response = self.client_for(self.etudiant).get(
            self.detail_url(conversation)
        )

        self.assertContains(response, 'ua-chat-suppr-form')
        self.assertContains(
            response,
            'Supprimer ce message ? Cette action est définitive.',
        )

    def test_bouton_de_suppression_uniquement_sur_les_propres_messages(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        mien = Message.objects.create(
            conversation=conversation, sender=self.etudiant, body='Le mien',
        )
        autre = Message.objects.create(
            conversation=conversation, sender=self.formateur, body='Le sien',
        )

        response = self.client_for(self.etudiant).get(
            self.detail_url(conversation)
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.delete_url(conversation, mien))
        self.assertNotContains(response, self.delete_url(conversation, autre))

    def test_sondage_expose_l_url_de_suppression_des_seuls_messages_propres(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        mien = Message.objects.create(
            conversation=conversation, sender=self.etudiant, body='Le mien',
        )
        autre = Message.objects.create(
            conversation=conversation, sender=self.formateur, body='Le sien',
        )

        response = self.client_for(self.etudiant).get(
            self.poll_url(conversation)
        )

        donnees = json.loads(response.content)
        relevés = {item['id']: item for item in donnees['messages']}
        self.assertEqual(
            relevés[str(mien.id)]['delete_url'],
            self.delete_url(conversation, mien),
        )
        self.assertEqual(relevés[str(autre.id)]['delete_url'], '')

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

    def test_poll_expose_laccuse_de_lecture_et_lannee(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        message = Message.objects.create(
            conversation=conversation, sender=self.etudiant, body='Lu ?',
        )
        client = self.client_for(self.etudiant)

        avant = json.loads(client.get(self.poll_url(conversation)).content)
        self.assertEqual(len(avant['messages']), 1)
        self.assertRegex(
            avant['messages'][0]['heure'],
            r'^\d{2}/\d{2}/\d{4} \d{2}:\d{2}$',
        )
        self.assertFalse(avant['messages'][0]['lu'])

        Message.objects.filter(pk=message.pk).update(read_at=timezone.now())
        apres = json.loads(client.get(self.poll_url(conversation)).content)

        self.assertTrue(apres['messages'][0]['lu'])
        self.assertNotEqual(apres['signature'], avant['signature'])

    def test_signature_du_sondage_change_a_larrivee_dun_message(self):
        conversation, _ = Conversation.pour(self.etudiant, self.formateur)
        client = self.client_for(self.etudiant)

        avant = json.loads(
            client.get(self.poll_url(conversation)).content
        )['signature']
        Message.objects.create(
            conversation=conversation, sender=self.formateur,
            body='Nouveau message',
        )
        apres = json.loads(
            client.get(self.poll_url(conversation)).content
        )

        self.assertNotEqual(apres['signature'], avant)
        self.assertEqual(apres['messages'][-1]['corps'], 'Nouveau message')

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


class MessagerieAdminTest(BusinessTestBase):
    """Les échanges sont consultables dans l'admin, effaçables avec une trace."""

    def setUp(self):
        super().setUp()
        self.tech = User.objects.create_superuser(
            email='tech@test.local', password=TEST_PASSWORD,
            first_name='Tech', last_name='Admin',
        )
        self.client = self.client_for(self.tech)
        self.conversation, _ = Conversation.pour(
            self.etudiant, self.formateur
        )
        self.message = Message.objects.create(
            conversation=self.conversation, sender=self.etudiant,
            body='Message visible dans ladministration',
        )

    def test_admin_liste_les_fils_et_les_messages(self):
        fils = self.client.get(reverse('admin:core_conversation_changelist'))
        self.assertEqual(fils.status_code, 200)
        self.assertContains(fils, self.conversation.pair_key)

        messages = self.client.get(reverse('admin:core_message_changelist'))
        self.assertEqual(messages.status_code, 200)
        self.assertContains(messages, 'Message visible dans ladministration')

    def test_admin_lit_le_message_complet_en_lecture_seule(self):
        response = self.client.get(reverse(
            'admin:core_message_change', args=[self.message.id]
        ))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Message visible dans ladministration')

    def test_admin_ne_peut_pas_supprimer_un_fil(self):
        response = self.client.get(reverse(
            'admin:core_conversation_delete', args=[self.conversation.id]
        ))
        self.assertEqual(response.status_code, 403)

    def test_admin_supprime_un_message_et_laudit(self):
        response = self.client.post(reverse(
            'admin:core_message_delete', args=[self.message.id]
        ), {'post': 'yes'})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Message.objects.filter(pk=self.message.pk).exists())
        journal = AuditLog.objects.get(action='MESSAGE_DELETE')
        self.assertEqual(journal.actor, self.tech)
        self.assertEqual(journal.entity_id, str(self.message.id))
        self.assertEqual(
            journal.before_summary['length'],
            len('Message visible dans ladministration'),
        )
