from flask import Flask
from flask_spectree import FlaskSpecTree


def test_extension_registers_on_app(app):
    assert "spectree" in app.extensions


def test_init_app_pattern():
    app = Flask(__name__)
    ext = FlaskSpecTree()
    ext.init_app(app)
    assert "spectree" in app.extensions


def test_spectree_title_from_config():
    app = Flask(__name__)
    app.config["SPECTREE_TITLE"] = "My API"
    ext = FlaskSpecTree(app)
    assert ext.spectree.spectree.title == "My API"


def test_spec_endpoint_available(client):
    resp = client.get("/apidoc/openapi.json")
    assert resp.status_code == 200
