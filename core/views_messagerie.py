"""Messagerie interne entre deux comptes connectés.

Pas de WebSocket : PythonAnywhere gratuit sert le site en WSGI avec un seul
worker. Le fil est donc actualisé par un court sondage HTTP (7 s), et chaque
envoi reste un POST classique avec redirection — bouton retour et historique
du navigateur conservent leur comportement habituel.
"""
import uuid

from django.contrib import messages
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .decorators import active_account_required
from .models import AccountStatus, Conversation, Message, Notification, User
from .utils import log_audit

LONGUEUR_MAX = 5000


def _destinataire(request):
    """Résout l'identifiant POST sans transformer une saisie libre en erreur 500."""
    valeur = request.POST.get('destinataire_id', '')
    try:
        uuid.UUID(str(valeur))
    except (ValueError, TypeError, AttributeError):
        raise Http404(_("Destinataire introuvable."))
    return get_object_or_404(
        User, pk=valeur, account_status=AccountStatus.ACTIVE
    )


@active_account_required
def conversation_list(request):
    """Boîte de réception : fils de l'utilisateur et recherche de destinataire."""
    recherche = (request.GET.get('q') or '').strip()
    destinataires = User.objects.filter(
        account_status=AccountStatus.ACTIVE
    ).exclude(pk=request.user.pk)
    if recherche:
        destinataires = destinataires.filter(
            Q(email__icontains=recherche)
            | Q(first_name__icontains=recherche)
            | Q(last_name__icontains=recherche)
            | Q(internal_code__icontains=recherche)
        )
    destinataires = destinataires.order_by('email')[:40]

    fils = []
    for conversation in Conversation.objects.filter(
        participants=request.user
    ).prefetch_related('participants', 'messages'):
        dernier = conversation.messages.select_related('sender').last()
        fils.append({
            'conversation': conversation,
            'interlocuteur': conversation.interlocuteur(request.user),
            'dernier': dernier,
            'non_lus': conversation.non_lus_pour(request.user),
        })

    return render(request, 'dashboard/messagerie/liste.html', {
        'fils': fils,
        'destinataires': destinataires,
        'recherche': recherche,
    })


@require_POST
@active_account_required
def conversation_start(request):
    """Ouvre (ou retrouve) le fil unique entre l'utilisateur et un collègue."""
    destinataire = _destinataire(request)
    if destinataire.pk == request.user.pk:
        return HttpResponseForbidden(
            _("Vous ne pouvez pas vous écrire à vous-même.")
        )

    conversation, cree = Conversation.pour(request.user, destinataire)
    if cree:
        log_audit(
            request, 'MESSAGE_CONVERSATION_OPEN', 'Conversation',
            conversation.id, after={'with': str(destinataire.pk)},
        )
    return redirect(
        'core:dashboard:messagerie-detail', conversation_id=conversation.id
    )


@active_account_required
def conversation_detail(request, conversation_id):
    """Fil de discussion, accessible seulement à ses deux participants."""
    conversation = get_object_or_404(
        Conversation, pk=conversation_id, participants=request.user
    )
    conversation.messages.filter(read_at__isnull=True).exclude(
        sender=request.user
    ).update(read_at=timezone.now())
    # La cloche et le fil disent la même chose : ouvrir la conversation éteint
    # aussi l'alerte « nouveau message » envoyée à ce fil.
    Notification.objects.filter(
        user=request.user,
        link=reverse(
            'core:dashboard:messagerie-detail', args=[conversation.id]
        ),
        is_read=False,
    ).update(is_read=True)

    messages = conversation.messages.select_related('sender').order_by(
        'created_at'
    )
    return render(request, 'dashboard/messagerie/fil.html', {
        'conversation': conversation,
        'interlocuteur': conversation.interlocuteur(request.user),
        'messages': messages,
        'nb_lus': messages.filter(
            sender=request.user, read_at__isnull=False
        ).count(),
        'longueur_max': LONGUEUR_MAX,
    })


@require_POST
@active_account_required
def message_create(request, conversation_id):
    """Envoie un message : une ligne d'audit et une notification interne."""
    conversation = get_object_or_404(
        Conversation, pk=conversation_id, participants=request.user
    )
    corps = (request.POST.get('body') or '').strip()
    if not corps:
        messages.error(request, _("Le message ne peut pas être vide."))
        return redirect(
            'core:dashboard:messagerie-detail', conversation_id=conversation.id
        )
    if len(corps) > LONGUEUR_MAX:
        messages.error(
            request,
            _("Le message ne peut pas dépasser %(limite)s caractères.")
            % {'limite': LONGUEUR_MAX},
        )
        return redirect(
            'core:dashboard:messagerie-detail', conversation_id=conversation.id
        )

    message = Message.objects.create(
        conversation=conversation, sender=request.user, body=corps
    )
    conversation.toucher()
    destinataire = conversation.interlocuteur(request.user)
    Notification.objects.create(
        user=destinataire,
        email=destinataire.email,
        title=str(_("Nouveau message de %(nom)s") % {
            'nom': request.user.display_label,
        }),
        message=corps[:200],
        link=reverse(
            'core:dashboard:messagerie-detail', args=[conversation.id]
        ),
        notification_type=Notification.Type.GENERAL,
    )
    log_audit(
        request, 'MESSAGE_SEND', 'Conversation', conversation.id,
        after={'to': str(destinataire.pk), 'length': len(message.body)},
    )
    return redirect(
        'core:dashboard:messagerie-detail', conversation_id=conversation.id
    )


@require_POST
@active_account_required
def message_delete(request, conversation_id, message_id):
    """Supprime un message envoyé, avec une ligne d'audit avant l'effacement.

    Seul l'expéditeur peut retirer sa propre phrase : effacer celle d'autrui
    reviendrait à réécrire l'historique de l'autre participant. L'accès au fil
    est vérifié d'abord, pour ne pas révéler l'existence d'un message tiers.
    """
    conversation = get_object_or_404(
        Conversation, pk=conversation_id, participants=request.user
    )
    message = get_object_or_404(
        Message, pk=message_id, conversation=conversation
    )
    if message.sender_id != request.user.pk:
        return HttpResponseForbidden(
            _("Vous ne pouvez supprimer que vos propres messages.")
        )

    log_audit(
        request, 'MESSAGE_DELETE', 'Message', message.id,
        before={
            'length': len(message.body),
            'conversation': str(conversation.id),
        },
    )
    message.delete()
    messages.success(request, _("Message supprimé."))
    return redirect(
        'core:dashboard:messagerie-detail', conversation_id=conversation.id
    )


@require_GET
@never_cache
@active_account_required
def messages_poll(request, conversation_id):
    """État du fil pour l'actualisation automatique, sans données d'autrui."""
    conversation = get_object_or_404(
        Conversation, pk=conversation_id, participants=request.user
    )
    relevés = []
    for message in conversation.messages.select_related('sender').order_by(
        'created_at'
    )[:100]:
        mien = message.sender_id == request.user.pk
        lu = message.read_at is not None
        relevés.append({
            'id': str(message.id),
            'auteur': message.sender.display_label,
            'corps': message.body,
            'heure': timezone.localtime(
                message.created_at
            ).strftime('%d/%m/%Y %H:%M'),
            'mien': mien,
            'lu': lu,
            'delete_url': reverse(
                'core:dashboard:messagerie-delete',
                args=[conversation.id, message.id],
            ) if mien else '',
        })
    # Un accusé de lecture ne change ni le nombre ni le dernier message : il
    # doit pourtant faire repartir le sondage, sinon le « Lu » n'apparaît jamais.
    lus = sum(1 for releve in relevés if releve['mien'] and releve['lu'])
    return JsonResponse({
        'messages': relevés,
        'signature': f'{len(relevés)}:'
                     f'{relevés[-1]["id"] if relevés else ""}:{lus}',
    })
