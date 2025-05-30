from flask import Flask
from app.api.routestwilio import voice_agent
from app.utils.logging_config import setup_logging

def create_app():
    app = Flask(__name__)
    setup_logging(app)
    app.register_blueprint(voice_agent)
    return app

if __name__ == "__main__":
    app = create_app()
    app.run(port=5000)
