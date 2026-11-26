"""Réconcilie le champ ``password_must_change`` avec la base de production.

La base en ligne a déjà appliqué l'ancienne migration 0028, qui a créé une
colonne ``NOT NULL`` sans valeur par défaut au niveau SQLite. Le code a ensuite
été ramené à un état sans ce champ, ce qui faisait échouer chaque création de
compte : l'INSERT n'envoyait pas la colonne obligatoire.

Cette migration ajoute le champ à l'état du projet et ne touche à la table que
si la colonne est absente (base neuve ou base de test). Sur la production, elle
est donc un simple no-op : la colonne existe déjà et reste à False. Elle
restaure aussi la ligne de rôle Direction supprimée par l'ancienne migration
0026, afin que la création d'utilisateur ne plante pas sur un rôle orphelin.
"""

from django.db import migrations, models


def restaurer_direction_si_absent(apps, schema_editor):
    """L'ancienne migration 0026 avait supprimé le rôle Direction en base."""
    role = apps.get_model('core', 'Role')
    role.objects.get_or_create(
        key='DIRECTION',
        defaults={'label': 'Direction', 'is_privileged': True},
    )


def ajouter_si_absent(apps, schema_editor):
    # L'état reçu par l'opération de base est celui d'avant l'AddField : on
    # construit donc le champ ici plutôt que de le lire sur le modèle historique.
    modele = apps.get_model('core', 'User')
    champ = models.BooleanField(
        default=False,
        verbose_name='Doit changer son mot de passe à la connexion',
    )
    champ.contribute_to_class(modele, 'password_must_change')
    table = modele._meta.db_table
    with schema_editor.connection.cursor() as curseur:
        colonnes = {
            colonne.name
            for colonne in schema_editor.connection.introspection.get_table_description(
                curseur, table
            )
        }
    if champ.column not in colonnes:
        schema_editor.add_field(modele, champ)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0025_fusion_secretariat'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='user',
                    name='password_must_change',
                    field=models.BooleanField(
                        default=False,
                        verbose_name='Doit changer son mot de passe à la connexion',
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(ajouter_si_absent, migrations.RunPython.noop),
                migrations.RunPython(
                    restaurer_direction_si_absent, migrations.RunPython.noop
                ),
            ],
        ),
    ]
