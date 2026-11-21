# Déploiement PythonAnywhere — Univers Academy

Marche à suivre pour mettre le projet `academy` en ligne sur
[PythonAnywhere](https://www.pythonanywhere.com) : une application web, une
base SQLite, le domaine `VOTRE-COMPTE.pythonanywhere.com` (HTTPS fourni).

> Remplacez `VOTRE-COMPTE` par votre identifiant PythonAnywhere. Le projet
> vit dans `/home/VOTRE-COMPTE/academy`.

---

## 1. Récupérer le code

Onglet « Consoles » → Bash :

```bash
cd /home/VOTRE-COMPTE
git clone https://github.com/klauza25/universe-academyPro.git academy
cd academy
```

Le dépôt GitHub est **privé**, mais le clonage fonctionne aussi avec un
compte gratuit : PythonAnywhere autorise github.com et le protocole `git`
dans sa liste d'adresses autorisées. Deux options :

- **HTTPS + jeton** : créez un *personal access token* GitHub (portée `repo`),
  puis lancez le `git clone` ci-dessus ; saisissez votre identifiant GitHub
  comme nom d'utilisateur et le jeton comme mot de passe.
- **SSH + clé** : `ssh-keygen`, copiez `~/.ssh/id_rsa.pub` dans les clés
  autorisées du compte GitHub, puis
  `git clone git@github.com:klauza25/universe-academyPro.git academy`.

Le gratuit ne fournit en revanche ni tâches planifiées (comptes créés après
le 15/01/2026), ni SMTP sortant : voir les sections 3 et 7.

## 2. Environnement virtuel et dépendances

```bash
mkvirtualenv academy --python=python3.13
# ou : python3.13 -m venv ~/.virtualenvs/academy && source ~/.virtualenvs/academy/bin/activate
pip install -r requirements.txt
```

Si la base reste SQLite, `psycopg2-binary` est inutile :

```bash
grep -v psycopg2 requirements.txt > /tmp/req-pa.txt && pip install -r /tmp/req-pa.txt
```

## 3. Fichier `.env`

```bash
cp .env.pythonanywhere.example .env
nano .env
```

Trois réglages à adapter absolument :

| Variable | Valeur |
|---|---|
| `SECRET_KEY` | **obligatoire et forte** (≥ 50 caractères) : en production le projet **refuse de démarrer** sans elle |
| `ALLOWED_HOSTS` | `VOTRE-COMPTE.pythonanywhere.com` |
| `CSRF_TRUSTED_ORIGINS` | `https://VOTRE-COMPTE.pythonanywhere.com` |

`DEBUG` reste `False`. Ne définissez **pas** `DATABASE_URL` : SQLite à la
racine (`db.sqlite3`), la sauvegarde est une simple copie du fichier.

Pour Gmail, un forfait payant est requis ; le mot de passe Gmail ne suffit
plus : créez un **mot de passe d'application** (compte Google → Sécurité →
Validation en deux étapes → Mots de passe d'application) et mettez-le dans
`EMAIL_HOST_PASSWORD`.

## 4. Initialisation

```bash
python manage.py migrer          # migrations (équivalent migrate + contrôle)
python manage.py seed_roles      # les rôles ne naissent pas des migrations
python manage.py create_superadmin --email admin@univers-academy.com \
    --password "MotDePasseFort123!" --secret "VALEUR_DE_SUPERADMIN_SETUP_SECRET"
python manage.py collectstatic --noinput
```

## 5. Onglet « Web » de PythonAnywhere

1. **Add a new web app** → « Manual configuration » → Python 3.13.
2. **Code** :
   - WSGI configuration file : `/home/VOTRE-COMPTE/academy/deploy/pythonanywhere_wsgi.py`
   - Working directory : `/home/VOTRE-COMPTE/academy`
   - Virtualenv : `/home/VOTRE-COMPTE/.virtualenvs/academy`
3. **Static files** — en production `DEBUG=False`, Django ne sert plus ses
   fichiers statiques : PythonAnywhere s'en charge via ces mappings.

| URL | Directory |
|---|---|
| `/static/` | `/home/VOTRE-COMPTE/academy/staticfiles/` |
| `/media/` | `/home/VOTRE-COMPTE/academy/media/` |

4. **Reload** (bouton vert en haut).

Le HTTPS est automatique sur `*.pythonanywhere.com` ; le projet pose déjà
`SECURE_PROXY_SSL_HEADER` et `SECURE_SSL_REDIRECT` (avec HSTS) quand
`DEBUG=False` — rien à ajouter, et pas de boucle de redirection.

## 6. Vérifier

- `https://VOTRE-COMPTE.pythonanywhere.com/` : le portail public s'affiche.
- `/admin/` : connexion avec le super administrateur créé.
- En cas d'erreur : onglet « Web » → « Error log (latest errors) ». Avec
  `DEBUG=False`, seuls les journaux serveur montrent les exceptions.

## 7. Synchronisation Google Sheets (forfait gratuit)

Les comptes gratuits créés après le 15/01/2026 n'ont **aucune tâche
planifiée** (les comptes plus anciens en ont une par jour). La synchronisation
se fait donc **à la main**, depuis l'interface :

1. Connectez-vous en tant que **super administrateur**.
2. Tableau de bord super administrateur → **« Synchroniser les classeurs »**.
3. La page de chargement affiche le téléchargement, l'analyse et l'import ;
   le compte rendu s'affiche ensuite, avec une trace dans le journal d'audit.

Le bouton est protégé par un verrou : un second clic pendant une synchro en
cours est refusé. Les feuilles Google restent publiques en lecture : aucun
compte de service n'est nécessaire.

Sur un **forfait payant**, la tâche quotidienne suivante reste disponible :

```bash
/home/VOTRE-COMPTE/.virtualenvs/academy/bin/python \
    /home/VOTRE-COMPTE/academy/deploy/pythonanywhere_sync.py
```

- Ce point d'entrée lance réellement la synchronisation (migrations puis
  import avec sauvegarde) seulement si au moins 72 heures se sont écoulées
  depuis sa dernière réussite. Un échec n'avance pas l'échéance : la prochaine
  tâche quotidienne réessaie.
- La date de dernière réussite est conservée hors du dépôt dans
  `~/.local/state/academy/google-sheets-sync-last-success`.
- Identifiants du compte de service, si les feuilles redeviennent privées :
  déposez le JSON **hors du dépôt**, p. ex.
  `/home/VOTRE-COMPTE/secrets/service-account.json`, désigné par la variable
  `GOOGLE_APPLICATION_CREDENTIALS` du `.env` (et les feuilles cibles par
  `CLASSEURS_GOOGLE_IDS`). Diagnostic sans réseau : `etat_google`.
- La fréquence et l'écrasement du miroir restent configurés par les mêmes
  options que sur ce poste (`--feuille`, `--importer`, `--ecrire`…).

## 8. Mises à jour d'une installation en ligne

```bash
cd /home/VOTRE-COMPTE/academy
git pull
source ~/.virtualenvs/academy/bin/activate
pip install -r requirements.txt
python manage.py migrer
python manage.py collectstatic --noinput
```

Puis **Reload** dans l'onglet « Web » (chaque changement de code l'exige).

## 9. Sauvegarde

Copier `/home/VOTRE-COMPTE/academy/db.sqlite3` (et le dossier `media/`)
suffit à sauvegarder toutes les données. Exemple à lancer à la main (ou via
une tâche quotidienne sur forfait payant) :

```bash
cp /home/VOTRE-COMPTE/academy/db.sqlite3 \
   /home/VOTRE-COMPTE/sauvegardes/db-$(date +\%F).sqlite3
```

## Checklist de livraison

- [ ] Dépôt cloné, virtualenv créé, `pip install -r requirements.txt` sans erreur
- [ ] `.env` présent : `DEBUG=False`, domaine du compte, `SECRET_KEY` ≥ 50 caractères
- [ ] `migrer` + `seed_roles` + `create_superadmin` exécutés
- [ ] `collectstatic` exécuté, mappings `/static/` et `/media/` posés
- [ ] WSGI pointant sur `deploy/pythonanywhere_wsgi.py`, virtualenv réglé
- [ ] Portail public, connexion, admin vérifiés sur le domaine final
- [ ] Synchronisation manuelle testée depuis le bouton super administrateur
- [ ] Copie de `db.sqlite3` conservée hors du dépôt
- [ ] (forfait payant) tâche quotidienne de synchro + JSON hors dépôt
