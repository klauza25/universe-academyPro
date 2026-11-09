# Rapport de test général — 06/11/2026

Périmètre : retrait de l'authentification Clerk, conservation de la connexion
locale, correction des dates de caisse, cohérence de la base de développement.

## 1. Résultat global

| Contrôle | Résultat |
|---|---|
| `python manage.py test core.tests` | **632 tests, 0 échec** (101 s) |
| `python manage.py check` | Aucun problème |
| `python manage.py makemigrations --check --dry-run` | Aucun changement détecté |
| `python manage.py showmigrations core` | 19 migrations appliquées, dont `0019_remove_user_clerk_user_id` |
| `python manage.py compiler_traductions --verifier` | 0 msgid à ajouter, 104 obsolètes, 0 sans traduction |
| `python manage.py verifier_i18n` | Interface entièrement balisée et traduite |
| Connexion locale (client Django) | `/login/` = 200, champs `identifier`, `password`, jeton CSRF présents, aucun `clerk` dans le HTML |
| Pages publiques `/`, `/login/`, `/register/` | 200, aucune mention Clerk |

La ligne `Exception: SMTP indisponible` affichée pendant la suite est le journal
d'un test qui simule volontairement une panne SMTP ; elle ne constitue pas un
échec.

## 2. Retrait de Clerk — vérifications

- `core/clerk.py` et `CLERK_SETUP.md` : **supprimés**.
- `univers_academy/settings.py` : bloc `CLERK_*`, calcul de l'API frontend et
  context processor retirés.
- `core/urls.py` : route `clerk/session/` supprimée.
- `core/views.py` : vue `clerk_session` supprimée ; `logout_view` ne redirige
  plus vers Clerk.
- `core/models.py` : champ `clerk_user_id` retiré ; migration `0019` appliquée.
- `core/middleware.py`, `core/context_processors.py`, `core/admin.py`,
  `core/forms.py`, `core/management/commands/audit_privileges.py` : références
  Clerk retirées.
- Gabarits `login.html`, `home.html`, `access_requests.html`, `user_detail.html` :
  aucun widget, script ou libellé Clerk.
- `requirements.txt` : `clerk-backend-api` retiré ; `.env` et `.env.example` :
  clés `CLERK_*` retirées.
- Tests : `test_public.py` vérifie l'absence de widget externe ;
  `test_auth_roles.py` couvre les comptes en attente sans Clerk (29 tests).
- Catalogue anglais : 104 msgid obsolètes retirés, traduction de la page
  d'accueil complétée.

Seules occurrences restantes, volontaires :

| Fichier | Raison |
|---|---|
| `core/migrations/0003_user_clerk_user_id.py` | Migration historique, non réécrite |
| `core/migrations/0004_...py` | Migration historique, non réécrite |
| `core/migrations/0019_remove_user_clerk_user_id.py` | Migration de retrait |
| `core/tests/test_public.py` | Assertion négative `assertNotIn('clerk', ...)` |
| `VALIDATION_METIER.md` | Mention de l'intégration retirée (traçabilité) |
| 14 lignes `AuditLog` `LOGIN_CLERK`/`REGISTER_CLERK` | Historique d'audit, non modifié |

## 3. Dates de caisse

| Contrôle | Résultat |
|---|---|
| Paiements datés après aujourd'hui (06/11/2026) | **0** |
| Écritures de caisse datées après aujourd'hui | **0** |
| Paiements dont la période est 2027 | 4 (période conservée) |
| Écritures de caisse datées 2027 | 0 |
| Contrôle `DATE_FUTURE` de `verifier_relations` | 0 |

## 4. Documents générés

Les trois DOCX ont été régénérés et ne contiennent plus aucune occurrence de
« Clerk » :

- `docs/Architecture_metier_Univers_Academy.docx` (modèles : 37, routes : 111,
  tests de référence : 632)
- `docs/Hebergement_Univers_Academy.docx`
- `docs/Mode_emploi_Univers_Academy.docx`

**Limite connue :** les PDF `docs/Hebergement_Univers_Academy.pdf` et
`docs/Mode_emploi_Univers_Academy.pdf` datent du 03/11/2026 et contiennent
encore 5 mentions de « Clerk » chacun. Leur régénération n'a pas pu aboutir sur
ce poste : LibreOffice/`soffice` est absent et l'automatisation Microsoft Word
se bloque à l'export PDF. Les DOCX sources sont à jour ; il reste à reconvertir
les PDF sur une machine disposant de LibreOffice :

```powershell
soffice --headless --convert-to pdf --outdir docs docs\Hebergement_Univers_Academy.docx
soffice --headless --convert-to pdf --outdir docs docs\Mode_emploi_Univers_Academy.docx
```

## 5. Qualité des données existantes (hors périmètre du retrait)

`python manage.py verifier_relations` signale **177 écarts** dans la base de
développement, antérieurs à ces modifications :

| Code | Nombre |
|---|---:|
| `ECRITURE_RECETTE_SANS_PAIEMENT` | 158 |
| `DOSSIER_DOUBLON` | 8 |
| `COMPTE_ACTIF_SANS_DOSSIER` | 6 |
| `TROPERCU` | 3 |
| `MENSUALITE_SANS_MOIS` | 2 |

`audit_privileges` signale en outre des comptes `PENDING_APPROVAL` portant déjà
un rôle `ETUDIANT` (comptes issus des imports), et 9 groupes sans formateur.
Ces points relèvent de la reprise des données métier, pas du code
d'authentification ; aucune donnée n'a été modifiée par ce rapport.

## 6. État Git

- Branche : `main`.
- Aucun commit ni push effectué.
- Le dépôt contient de nombreuses modifications concurrentes (114 fichiers
  modifiés, 25 non suivis), dont les migrations `0015`–`0018`, les modules
  année académique / paramètres / relations et leurs tests. Ces fichiers n'ont
  pas été réécrits par le présent travail.
- Fichiers générés exclus du versionnement : `db.sqlite3`, `backups/`,
  `.env*`, `docs/donnees/`, `__pycache__`.

## 7. Commandes exécutées

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py compiler_traductions --verifier
python manage.py verifier_i18n
python manage.py test core.tests
python manage.py verifier_relations
python manage.py audit_privileges
python docs\generate_architecture_docx.py
python docs\generate_hebergement_docx.py
python docs\generate_mode_emploi_docx.py
```
