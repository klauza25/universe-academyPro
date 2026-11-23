"""Retire le rôle Direction.

Le rôle Direction est supprimé du système. Les comptes qui le portaient sont
basculés vers Assistant administratif, et les demandes d'accès référençant
Direction sont remappées vers Assistant administratif. La ligne de rôle
Direction est supprimée après migration des affectations.

La racine ``UA-DIR`` permet de revenir en arrière : seuls les comptes portant
encore ce code interne retrouvent le rôle Direction.
"""

from django.db import migrations

RACINE_DIRECTION = 'UA-DIR'


def retirer_direction(apps, schema_editor):
    Role = apps.get_model('core', 'Role')
    UserRole = apps.get_model('core', 'UserRole')
    AccessRequest = apps.get_model('core', 'AccessRequest')

    assistant = Role.objects.filter(key='ASSISTANT_ADMIN').first()
    direction = Role.objects.filter(key='DIRECTION').first()

    if assistant and direction:
        for lien in UserRole.objects.filter(role=direction).select_related('user'):
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
        direction.delete()

    AccessRequest.objects.filter(requested_role='DIRECTION').update(
        requested_role='ASSISTANT_ADMIN'
    )
    AccessRequest.objects.filter(assigned_role='DIRECTION').update(
        assigned_role='ASSISTANT_ADMIN'
    )


def restaurer_direction(apps, schema_editor):
    Role = apps.get_model('core', 'Role')
    UserRole = apps.get_model('core', 'UserRole')
    AccessRequest = apps.get_model('core', 'AccessRequest')

    assistant = Role.objects.filter(key='ASSISTANT_ADMIN').first()
    direction, _ = Role.objects.get_or_create(
        key='DIRECTION',
        defaults={'label': 'Direction', 'is_privileged': True},
    )

    if assistant:
        for lien in UserRole.objects.filter(role=assistant).select_related('user'):
            if not (lien.user.internal_code or '').startswith(RACINE_DIRECTION):
                continue
            UserRole.objects.get_or_create(
                user_id=lien.user_id, role=direction,
                defaults={'assigned_by_id': lien.assigned_by_id},
            )
            lien.delete()

    # Les demandes remappées ne sont pas restaurées automatiquement : le sens
    # original DIRECTION a été absorbé par ASSISTANT_ADMIN.


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0025_fusion_secretariat'),
    ]

    operations = [
        migrations.RunPython(retirer_direction, restaurer_direction),
    ]
