"""Le poste « Secrétaire » rejoint l'Assistant administratif.

Comme pour l'Accueil et la Caisse, la ligne ``SECRETAIRE`` reste en base pour
que l'historique (audit, demandes d'accès, paiements encaissés) garde son sens.
Les affects en service sont transférées à ``ASSISTANT_ADMIN`` sans perdre
l'auteur de la nomination : ``assigned_by`` est repris tel quel, ou comblé si
le compte avait déjà les deux rôles.

La racine ``UA-SEC`` permet de revenir en arrière sans table d'union : seuls
les comptes portant encore ce code interne retrouvent l'ancien rôle.
"""

from django.db import migrations

RACINE_SECRETAIRE = 'UA-SEC'


def fusionne(apps, schema_editor):
    Role = apps.get_model('core', 'Role')
    UserRole = apps.get_model('core', 'UserRole')

    assistant = Role.objects.filter(key='ASSISTANT_ADMIN').first()
    secretaire = Role.objects.filter(key='SECRETAIRE').first()
    if assistant is None or secretaire is None:
        return

    for lien in UserRole.objects.filter(role=secretaire).select_related('user'):
        fusion, created = UserRole.objects.get_or_create(
            user_id=lien.user_id, role=assistant,
            defaults={'assigned_by_id': lien.assigned_by_id},
        )
        if (
            not created and fusion.assigned_by_id is None
            and lien.assigned_by_id is not None
        ):
            fusion.assigned_by_id = lien.assigned_by_id
            fusion.save(update_fields=['assigned_by'])
        lien.delete()


def demele(apps, schema_editor):
    Role = apps.get_model('core', 'Role')
    UserRole = apps.get_model('core', 'UserRole')

    assistant = Role.objects.filter(key='ASSISTANT_ADMIN').first()
    secretaire = Role.objects.filter(key='SECRETAIRE').first()
    if assistant is None or secretaire is None:
        return

    for lien in UserRole.objects.filter(role=assistant).select_related('user'):
        if not (lien.user.internal_code or '').startswith(RACINE_SECRETAIRE):
            continue
        UserRole.objects.get_or_create(
            user_id=lien.user_id, role=secretaire,
            defaults={'assigned_by_id': lien.assigned_by_id},
        )
        lien.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0024_droits_gestion_assistant'),
    ]

    operations = [
        migrations.RunPython(fusionne, demele),
    ]
