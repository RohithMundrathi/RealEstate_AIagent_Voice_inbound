from flask import Flask
from app.api.routestwilio import voice_agent
from app.utils.logging_config import setup_logging  # If utils is sibling to app and also has __init__.py

app = Flask(__name__)
setup_logging(app)
app.register_blueprint(voice_agent)

@app.route("/test")
def hello():
    return "hello this is test working!"

if __name__ == "__main__":
    app.run(port=5000)
