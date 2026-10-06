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

La liste est exposée dans [requirements.txt](requirements.txt). Elle comprend Flask, Flask-SQLAlchemy, Flask-Migrate, Flask-Login, Flask-WTF, Flask-Mail, Flask-Babel, APScheduler, sqlite et outils pour les exports Excel/PDF.

## Lancement local

1. Créer un environnement virtuel : `python -m venv .venv`
2. Activer l'environnement : `.venv\Scripts\Activate.ps1`
3. Installer les dépendances : `pip install -r requirements.txt`
4. Copier le fichier environnement : `Copy-Item .env.example .env`
5. Lancer le serveur : `python run.py`

L'application est alors accessible sur http://127.0.0.1:5000.

## Étape 1 réalisée

- Structure applicative Flask factory + blueprints
- Support multi-devise et multilingue par défaut
- Modèles SQLAlchemy complets pour les comptes, transactions, budgets, objectifs, dettes, devises, taux de change et journal
- Données de base initiales (devises + catégories système)
- Migrations Flask-Migrate préparées
- Design system et base de Tailwind / HTMX / Alpine
- Page d'accueil de démonstration

## Remarques de conception

- Les calculs monétaires sont centralisés dans `app/services/money.py` pour rester testables.
- Les montants sont traités en entiers selon la plus petite unité de devise.
- Le projet utilise un design mobile-first avec une architecture prête à accueillir les prochaines étapes.
