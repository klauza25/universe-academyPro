"""L'assistant administratif gère les comptes et les attributions de rôles.

Les droits sont ajoutés à la matrice sans toucher aux autres postes : le code
applique déjà la nouvelle règle, la migration rend les cases correspondantes
visibles et coché chez les installations existantes.
"""

from django.db import migrations

DROITS = (
    'users.read',
    'users.create',
    'users.edit',
    'roles.manage',
    'access_requests.review',
)


def accorder(apps, schema_editor):
    Role = apps.get_model('core', 'Role')
    Permission = apps.get_model('core', 'Permission')
    RolePermission = apps.get_model('core', 'RolePermission')

    role = Role.objects.filter(key='ASSISTANT_ADMIN').first()
    if role is None:
        return
    for cle in DROITS:
        permission, ___ = Permission.objects.get_or_create(
            key=cle, defaults={'description': cle},
        )
        RolePermission.objects.get_or_create(role=role, permission=permission)


def retirer(apps, schema_editor):
    Role = apps.get_model('core', 'Role')
    RolePermission = apps.get_model('core', 'RolePermission')

    role = Role.objects.filter(key='ASSISTANT_ADMIN').first()
    if role is None:
        return
    RolePermission.objects.filter(
        role=role, permission__key__in=DROITS,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0023_notification_link'),
    ]

    operations = [
        migrations.RunPython(accorder, retirer),
    ]
