from flask import Flask
from flask_cors import CORS

from .config import Config
from .models import db


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    CORS(app, resources={r"/api/*": {"origins": "*"}})
    db.init_app(app)

    from .api.campaigns import bp as campaigns_bp
    from .api.execution import bp as execution_bp
    from .api.projects import bp as projects_bp
    from .api.reports import bp as reports_bp
    from .api.scenarios import bp as scenarios_bp

    app.register_blueprint(projects_bp, url_prefix="/api")
    app.register_blueprint(campaigns_bp, url_prefix="/api")
    app.register_blueprint(scenarios_bp, url_prefix="/api")
    app.register_blueprint(execution_bp, url_prefix="/api")
    app.register_blueprint(reports_bp, url_prefix="/api")

    with app.app_context():
        db.create_all()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app
