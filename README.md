# Agent universel de test E2E

L’interface React permet de gérer des projets et leurs cibles, d’explorer une application, de revoir les scénarios générés et de lancer une campagne Playwright. Flask conserve les campagnes et les résultats en base. Les preuves et les rapports HTML sont enregistrés dans `storage/`.

## Installation locale

Prérequis sur Windows pour les commandes ci-dessous. Installez Python 3.11 et Node.js 22.12 ou plus récent. Pour utiliser PostgreSQL, créez une base vide et renseignez sa chaîne de connexion dans `backend/.env`.

Depuis la racine du projet, dans PowerShell.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium

npm.cmd --prefix frontend ci
```

Pour une démonstration sans PostgreSQL, définissez `DATABASE_URL=sqlite:///agent_e2e.db` dans `backend/.env`. Renseignez `GROQ_API_KEY` pour activer la génération par IA. En l’absence de clé, le moteur propose des scénarios de navigation à partir des pages observées.

## Démarrer la plateforme

Exécutez chaque commande dans un terminal distinct, depuis la racine du projet.

```powershell
.\.venv\Scripts\python.exe backend/run.py
```

```powershell
npm.cmd --prefix frontend run dev
```

Pour tester l’application de démonstration fournie, démarrez aussi ce serveur.

```powershell
.\.venv\Scripts\python.exe demo_app/app.py
```

Ouvrez l’adresse affichée par Vite, généralement `http://localhost:5173`. Créez un projet et ajoutez la cible `http://127.0.0.1:5001/`. Créez une campagne, lancez l’exploration, générez les scénarios et approuvez ceux à exécuter. Après l’exécution, l’onglet **Résultats** donne accès aux étapes, aux preuves et au rapport HTML.

## Vérifier le parcours

```powershell
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m pytest -q backend/tests
```

Le test démarre les serveurs sur des ports locaux temporaires et utilise une base SQLite jetable. Il parcourt le workflow dans Chromium et vérifie l’accès au rapport et aux preuves.

## Tester deux comptes sur votre site

1. Démarrez votre site de test et la plateforme. Configurez `GROQ_API_KEY` dans `backend/.env`, puis redémarrez Flask si vous venez d’ajouter la clé.
2. Dans **Projets**, choisissez votre projet. Ajoutez une cible ou sélectionnez la cible existante et cliquez sur **Modifier**. Saisissez l’URL de départ de votre site. La page de connexion doit être accessible depuis cette URL. Vous pouvez aussi renseigner directement l’URL de connexion.
3. Ouvrez **Identifiants de test**. Cliquez quatre fois sur **Ajouter une variable**, puis renseignez les paires suivantes. Saisissez les valeurs réelles uniquement dans le champ **Valeur**.

   | Nom de variable | Valeur à saisir |
   | --- | --- |
   | `account_1_email` | Adresse du compte de test 1 |
   | `account_1_password` | Mot de passe du compte de test 1 |
   | `account_2_email` | Adresse du compte de test 2 |
   | `account_2_password` | Mot de passe du compte de test 2 |

4. Enregistrez la cible. Dans **Nouvelle campagne**, collez le texte ci-dessous dans **Objectif facultatif**. Remplacez les passages entre crochets par le comportement attendu selon vos règles métier, par exemple « accès autorisé » ou « accès refusé et redirection vers l’accueil ». Ajoutez l’URL exacte de la page d’administration si elle est connue et qu’elle n’est accessible qu’après connexion.

   > Crée deux scénarios, chacun dans une session vierge.
   >
   > **Compte 1.** Connecte-toi avec {account_1_email} et {account_1_password}. Depuis l’application, ouvre la page d’administration des utilisateurs. Le résultat attendu est [comportement attendu pour le compte 1]. Vérifie ce résultat avec un élément visible ou une URL. Si l’accès est attendu et que le total global des utilisateurs est affiché, relève-le avec une étape read_text ciblant ce total. Déconnecte-toi et vérifie que le formulaire de connexion réapparaît.
   >
   > **Compte 2.** Connecte-toi avec {account_2_email} et {account_2_password}. Ouvre la même page. Le résultat attendu est [comportement attendu pour le compte 2]. Vérifie ce résultat. Si l’accès est attendu et que le total global est affiché, relève-le de la même façon. Déconnecte-toi et vérifie le retour au formulaire.
   >
   > Le total doit être lu depuis l’interface. Si seules les lignes de la page courante sont visibles, ne les assimile pas au total global. Marque les étapes fondées sur des éléments non observés comme des hypothèses.

5. Cliquez sur **Créer la campagne**, **Explorer la cible**, puis **Générer les scénarios**. Dans **Scénarios**, vérifiez que chaque compte a son propre scénario et que les actions `fill` utilisent les bonnes variables. Vérifiez aussi le lien ou le bouton de déconnexion, les assertions d’accès et le sélecteur de l’étape `read_text`. L’exploration initiale se fait sans connexion. Les sélecteurs des pages après connexion peuvent donc nécessiter une correction via **Modifier**.
6. Approuvez les deux scénarios, puis cliquez sur **Exécuter les scénarios approuvés**. Dans **Résultats → Étapes exécutées**, cherchez **Texte relevé** sous le scénario correspondant. Le rapport HTML reprend cette observation. Si l’accès est refusé comme prévu, le résultat attendu est ce refus et aucun total n’est à relever.

Les variables sont enregistrées dans la base locale et leurs valeurs sont masquées dans le formulaire après sauvegarde. Utilisez des comptes jetables et ne mettez jamais leurs valeurs dans l’objectif envoyé à Groq. Pour les cibles avec identifiants, les exécutions conservent les journaux filtrés et désactivent les captures, les vidéos et les traces. Si vous avez déjà partagé les mots de passe réels, changez-les avant le test.





Crée exactement deux scénarios indépendants, chacun dans une session de navigateur vierge. Utilise les variables d’identifiants telles quelles dans les actions fill. Pour soumettre chaque formulaire, cible le bouton de connexion par son nom visible ou par un sélecteur précis dans le formulaire. N’utilise pas le sélecteur générique button.

Scénario 1 — Accès administrateur autorisé

1. Ouvre http://localhost:5174/admin. Vérifie avec url_equals que la redirection mène à http://localhost:5174/admin/login.
2. Renseigne {account_admin_email} et {account_admin_password}, puis soumets le formulaire. Vérifie avec url_equals que l’URL devient http://localhost:5174/admin. Si le navigateur reste sur /admin/login, considère la connexion comme non confirmée.
3. Ouvre http://localhost:5174/admin/users. Vérifie avec url_equals que cette URL est atteinte et, si possible, vérifie qu’un élément propre à la gestion des utilisateurs est visible.
4. Si le total global des utilisateurs est affiché, relève son texte avec read_text en ciblant l’élément qui affiche ce total. Ne compte pas les lignes visibles d’une liste paginée. Si le sélecteur du total n’est pas connu, indique qu’il doit être confirmé avant l’exécution.
5. Déconnecte-toi avec le contrôle prévu par l’application. Vérifie que le formulaire de connexion administrateur est de nouveau visible.

Scénario 2 — Accès administrateur refusé à un utilisateur standard

1. Ouvre http://localhost:5174/login. Connecte-toi avec {account_user_email} et {account_user_password}.
2. Vérifie que la connexion a réussi avec un indicateur réservé aux utilisateurs connectés, comme le menu du compte ou un bouton de déconnexion. Si la connexion n’est pas confirmée, considère le test d’accès comme non concluant.




on va se connecter en premier dans http://localhost:5174/login avec l'adresse {account_1_email} et le mot de passe {account_1_password} puis on va acceder a la page http://localhost:5174/products verifier le nom de produit {item} est visible et acceder a la page de produit lire le prix d'achat et l'afficher puis ajouter 3 au panier ensuite on va aller a http://localhost:5174/cart pour verifier que l'element est au panier et confirmer la reservation qui va nous envoyer a la page http://localhost:5174/checkout ou on va afficher le total et puis confirmer en cliquant sur le bouton de confirmation , elle va nous envoyer a la page http://localhost:5174/profile ou il s'jaoute un nouveau element en attente dans mes demandes appele {item} puis on va se deconnecter qui va nous redirectionner vers http://localhost:5174/
