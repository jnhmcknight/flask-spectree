import json

import pytest
from flask import Flask
from flask_spectree import FlaskSpecTree


def test_extension_registers_on_app(app):
    assert "spectree" in app.extensions


def test_init_app_pattern():
    app = Flask(__name__)
    ext = FlaskSpecTree()
    ext.init_app(app)
    assert "spectree" in app.extensions


def test_register_alias():
    """register() is an alias for init_app()."""
    app = Flask(__name__)
    ext = FlaskSpecTree()
    ext.register(app)
    assert "spectree" in app.extensions


def test_spectree_title_from_config():
    app = Flask(__name__)
    app.config["SPECTREE_TITLE"] = "My API"
    ext = FlaskSpecTree(app=app)
    assert ext.config.title == "My API"


def test_spectree_default_title():
    app = Flask(__name__)
    ext = FlaskSpecTree(app=app)
    assert ext.config.title == "Service API Document"


def test_spec_endpoint_available(client):
    resp = client.get("/apidoc/openapi.json")
    assert resp.status_code == 200


def test_spec_endpoint_returns_json(client):
    resp = client.get("/apidoc/openapi.json")
    data = json.loads(resp.data)
    assert "openapi" in data
    assert "info" in data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@pytest.fixture()
def cli_runner(app):
    return app.test_cli_runner()


def test_cli_export_json(cli_runner):
    result = cli_runner.invoke(args=["spec", "export", "--format", "json"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert "openapi" in parsed


def test_cli_export_raw(cli_runner):
    result = cli_runner.invoke(args=["spec", "export", "--format", "raw"])
    assert result.exit_code == 0
    assert "openapi" in result.output


def test_cli_export_flat(cli_runner):
    result = cli_runner.invoke(args=["spec", "export", "--format", "json", "--flat"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert "openapi" in parsed


def test_cli_flatten_command(cli_runner, tmp_path):
    input_spec = {
        "openapi": "3.1.0",
        "info": {"title": "Test", "version": "0.1.0"},
        "components": {
            "schemas": {
                "Foo.abc1234": {"type": "object"},
            }
        },
    }
    infile = tmp_path / "spec.json"
    infile.write_text(json.dumps(input_spec))
    outfile = tmp_path / "flat.json"

    result = cli_runner.invoke(
        args=["spec", "flatten", "-i", str(infile), "-o", str(outfile)]
    )
    assert result.exit_code == 0
    output = json.loads(outfile.read_text())
    assert "Foo" in output["components"]["schemas"]
