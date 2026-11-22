"""Application cible de démonstration pour valider l'agent E2E (multi-pages, formulaires, recherche, auth)."""
from flask import Flask, redirect, render_template_string, request, session, url_for

app = Flask(__name__)
app.secret_key = "demo-secret"

BASE = """
<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>{title}</title><style>
body{{font-family:sans-serif;max-width:800px;margin:24px auto;padding:0 16px;color:#222}}
nav{{background:#2c3e50;padding:10px 16px;border-radius:6px;margin-bottom:20px}}
nav a{{color:#ecf0f1;margin-right:16px;text-decoration:none}}
.error{{color:#c0392b}} .ok{{color:#27ae60}} .warn{{background:#fff3cd;padding:8px;border-radius:4px}}
input,select,textarea{{padding:6px 8px;margin:4px 0;width:100%;box-sizing:border-box}}
button{{background:#2980b9;color:#fff;border:0;padding:8px 16px;border-radius:4px;cursor:pointer}}
</style></head><body>
<nav><a href="/">Accueil</a><a href="/form">Formulaire</a><a href="/search">Recherche</a>
<a href="/products">Produits</a><a href="/about">À propos</a><a href="/login">Connexion</a></nav>
{content}
</body></html>
"""


def page(title, content):
    return render_template_string(BASE.format(title=title, content=content))


@app.route("/")
def index():
    return page(
        "Accueil",
        """<h1>Boutique de démonstration</h1>
        <p>Bienvenue sur l'application cible de test.</p>
        <ul>
          <li><a href="/form">Formulaire d'inscription</a></li>
          <li><a href="/search">Recherche de produits</a></li>
          <li><a href="/products">Catalogue</a></li>
          <li><a href="/about">À propos</a></li>
        </ul>""",
    )


@app.route("/form", methods=["GET", "POST"])
def form():
    errors = []
    values = {"name": "", "email": "", "country": ""}
    if request.method == "POST":
        values = {k: request.form.get(k, "") for k in values}
        if not values["name"].strip():
            errors.append("Le nom est obligatoire.")
        if not values["email"].strip():
            errors.append("L'email est obligatoire.")
        elif "@" not in values["email"]:
            errors.append("L'email est invalide.")
        if not errors:
            return page(
                "Inscription réussie",
                f"""<h1 class="ok">Inscription réussie</h1>
                <p>Merci {values['name']}, votre inscription a été enregistrée.</p>
                <a href="/">Retour à l'accueil</a>""",
            )
    error_html = "".join(f'<p class="error">{e}</p>' for e in errors)
    return page(
        "Formulaire d'inscription",
        f"""<h1>Formulaire d'inscription</h1>{error_html}
        <form method="post" action="/form">
          <label for="name">Nom complet *</label>
          <input id="name" name="name" placeholder="Jean Dupont" value="{values['name']}">
          <label for="email">Email *</label>
          <input id="email" name="email" type="email" placeholder="jean@example.com" value="{values['email']}">
          <label for="country">Pays</label>
          <select id="country" name="country">
            <option value="">-- Choisir --</option>
            <option value="fr" {'selected' if values['country']=='fr' else ''}>France</option>
            <option value="be" {'selected' if values['country']=='be' else ''}>Belgique</option>
            <option value="ch" {'selected' if values['country']=='ch' else ''}>Suisse</option>
          </select>
          <button type="submit">S'inscrire</button>
        </form>""",
    )


PRODUCTS = [
    {"id": 1, "name": "Clavier mécanique", "price": 79},
    {"id": 2, "name": "Souris ergonomique", "price": 45},
    {"id": 3, "name": "Écran 27 pouces", "price": 249},
    {"id": 4, "name": "Casque audio", "price": 129},
]


@app.route("/search", methods=["GET", "POST"])
def search():
    query = request.args.get("q", "").strip()
    results = [p for p in PRODUCTS if query.lower() in p["name"].lower()] if query else PRODUCTS
    rows = "".join(
        f'<li><a href="/products/{p["id"]}">{p["name"]} — {p["price"]} €</a></li>'
        for p in results
    )
    return page(
        "Recherche",
        f"""<h1>Recherche de produits</h1>
        <form method="get" action="/search">
          <input id="q" name="q" placeholder="Rechercher un produit…" value="{query}">
          <button type="submit">Rechercher</button>
        </form>
        <p>{len(results)} résultat(s)</p>
        <ul id="results">{rows or '<li>Aucun résultat</li>'}</ul>""",
    )


@app.route("/products")
def products():
    rows = "".join(
        f'<li><a href="/products/{p["id"]}">{p["name"]} — {p["price"]} €</a></li>'
        for p in PRODUCTS
    )
    return page("Catalogue", f"<h1>Catalogue</h1><ul>{rows}</ul>")


@app.route("/products/<int:pid>")
def product_detail(pid):
    product = next((p for p in PRODUCTS if p["id"] == pid), None)
    if not product:
        return page("Introuvable", '<h1 class="error">Produit introuvable</h1>'), 404
    return page(
        product["name"],
        f"""<h1>{product['name']}</h1>
        <p>Prix : <span id="price">{product['price']} €</span></p>
        <button id="add-cart">Ajouter au panier</button>
        <p id="cart-msg" class="ok" style="display:none">Ajouté au panier</p>
        <script>
        document.getElementById('add-cart').addEventListener('click', function() {{
          document.getElementById('cart-msg').style.display = 'block';
        }});
        </script>""",
    )


@app.route("/about")
def about():
    return page(
        "À propos",
        """<h1>À propos</h1>
        <p>Application de démonstration pour l'évaluation de l'agent de tests E2E.</p>
        <p class="warn">Environnement de test — aucune donnée réelle.</p>""",
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("username") == "demo" and request.form.get("password") == "demo":
            session["user"] = "demo"
            return redirect(url_for("dashboard"))
        error = "Identifiants incorrects."
    error_html = f'<p class="error">{error}</p>' if error else ""
    return page(
        "Connexion",
        f"""<h1>Connexion</h1>{error_html}
        <form method="post" action="/login">
          <label for="username">Utilisateur</label>
          <input id="username" name="username" placeholder="demo">
          <label for="password">Mot de passe</label>
          <input id="password" name="password" type="password" placeholder="demo">
          <button type="submit">Se connecter</button>
        </form>
        <p class="warn">Compte de test : demo / demo</p>""",
    )


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    return page(
        "Tableau de bord",
        f"""<h1>Bonjour {session['user']}</h1>
        <p class="ok">Connexion réussie.</p>
        <a href="/logout">Se déconnecter</a>""",
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
