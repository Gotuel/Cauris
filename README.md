# Cauris

Cauris est une application Flask de gestion monétaire personnelle pensée pour les marchés africains, avec devise par défaut XAF, langue par défaut français, et architecture prête pour l'extension multi-utilisateur, multi-devise, multilingue et PWA.

## Arborescence du projet

cauris/
├── app/
│   ├── __init__.py
│   ├── extensions.py
│   ├── main.py
│   ├── models/
│   ├── auth/
│   │   ├── forms.py
│   │   └── services.py
│   ├── accounts/
│   ├── transactions/
│   ├── budgets/
│   ├── goals/
│   ├── debts/
│   ├── dashboard/
│   ├── reports/
│   ├── services/
│   ├── translations/
│   ├── templates/
│   ├── static/
│   └── manifest.json
├── migrations/
├── tests/
├── config.py
├── requirements.txt
├── .env.example
├── README.md
├── run.py
├── tailwind.config.js
└── .gitignore

## Dépendances

La liste est exposée dans [requirements.txt](requirements.txt). Elle comprend Flask, Flask-SQLAlchemy, Flask-Migrate, Flask-Login, Flask-WTF, Flask-Mail, Flask-Babel, APScheduler, les pilotes SQLite/PostgreSQL et les outils pour les exports Excel/PDF.

## Lancement local

1. Créer un environnement virtuel : `python -m venv .venv`
2. Activer l'environnement : `.venv\Scripts\Activate.ps1`
3. Installer les dépendances : `python -m pip install -r requirements.txt`
4. Copier le fichier environnement : `Copy-Item .env.example .env`
5. Appliquer les migrations : `python -m flask db upgrade`
6. Lancer le serveur : `python run.py`

L'application est alors accessible sur http://127.0.0.1:5000.

## Étapes réalisées

- **Étape 1** : structure Flask factory + blueprints, configuration, modèles, données initiales, migrations et base du design system.
- **Étape 2** : inscription avec confirmation d’adresse e-mail, connexion/déconnexion, limite de tentatives, réinitialisation par lien signé et expirant, profil (langue, devise, thème), changement de mot de passe et suppression confirmée du compte.
- **Étape 3** : gestion des comptes et soldes, catégories/sous-catégories, transactions filtrables/paginées avec reçus, et virements atomiques y compris entre devises.

Les mots de passe sont hachés avec Argon2. Les comptes non confirmés ne peuvent pas se connecter. Les erreurs d’envoi de courrier sont journalisées côté serveur et affichées clairement à l’utilisateur; le compte créé reste disponible pour une nouvelle tentative d’envoi à la connexion.

Les montants saisis sont convertis en unités mineures entières selon la devise. Les taux utilisent la parité fixe XAF/XOF–EUR, sinon `open.er-api.com`; les taux quotidiens sont enregistrés, et le dernier taux stocké est utilisé si le fournisseur est inaccessible. Chaque transaction conserve son taux et la devise de base qui servait à son enregistrement, afin que les préférences monétaires modifiées plus tard ne réécrivent pas l’historique. Les reçus sont limités à 8 Mo et aux formats PDF, JPEG, PNG et WebP; ils ne sont servis qu’à leur propriétaire.

## Configuration des e-mails et sécurité

En local, configurez `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD` et les options TLS dans `.env` pour utiliser un serveur SMTP de test ou votre fournisseur de messagerie. Si `SECRET_KEY` reste vide, le développement génère une clé temporaire à chaque processus; définissez-en une stable pour conserver les sessions après un redémarrage. Générez-la avec `python -c "import secrets; print(secrets.token_hex(32))"`. Les liens de confirmation et de réinitialisation expirent après `SECURITY_TOKEN_MAX_AGE` secondes (1 heure par défaut). En production, fournissez une `SECRET_KEY` forte et utilisez HTTPS; les cookies de session y sont marqués `Secure`.

## Tests

Lancez la suite avec `python -m pytest -q`. Les tests d’authentification utilisent une base SQLite en mémoire et n’envoient pas de vrais e-mails.

## Remarques de conception

- Les calculs monétaires sont centralisés dans `app/services/money.py` pour rester testables.
- Les montants sont traités en entiers selon la plus petite unité de devise.
- Le projet utilise un design mobile-first avec une architecture prête à accueillir les prochaines étapes.
