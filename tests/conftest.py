import pytest
from flask import Flask
from flask_spectree import FlaskSpecTree


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    FlaskSpecTree(app=app)
    return app


@pytest.fixture()
def client(app):
    return app.test_client()
