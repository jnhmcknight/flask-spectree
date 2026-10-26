import json
import subprocess

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


def test_cli_export_raw_to_file(cli_runner, tmp_path):
    outfile = tmp_path / "raw.txt"
    result = cli_runner.invoke(
        args=["spec", "export", "--format", "raw", "-o", str(outfile)]
    )
    assert result.exit_code == 0
    assert "openapi" not in result.output
    assert "openapi" in outfile.read_text()


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def test_cli_export_ts_failure(cli_runner, monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _completed(1, stderr="boom")
    )
    result = cli_runner.invoke(args=["spec", "export", "--format", "ts"])
    assert result.exit_code == 1
    assert "exited with status 1" in result.output


def test_cli_export_ts_without_npx(cli_runner, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("npx")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = cli_runner.invoke(args=["spec", "export", "--format", "ts"])
    assert result.exit_code == 1
    assert "npx was not found" in result.output


def test_cli_export_json_to_file(cli_runner, tmp_path):
    outfile = tmp_path / "spec.json"
    result = cli_runner.invoke(args=["spec", "export", "-o", str(outfile)])
    assert result.exit_code == 0
    assert "openapi" in json.loads(outfile.read_text())


def test_cli_export_ts_stdout(cli_runner, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return _completed(stdout="export type Foo = {};")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = cli_runner.invoke(args=["spec", "export", "--format", "ts"])
    assert result.exit_code == 0
    assert "export type Foo" in result.output

    cmd, kwargs = calls[0]
    assert cmd[:2] == ["npx", "openapi-typescript"]
    assert "-o" not in cmd
    assert "openapi" in json.loads(kwargs["input"])


def test_cli_export_ts_to_file(cli_runner, monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _completed()

    monkeypatch.setattr(subprocess, "run", fake_run)
    outfile = tmp_path / "api.d.ts"
    result = cli_runner.invoke(
        args=["spec", "export", "--format", "ts", "--flat", "-o", str(outfile)]
    )
    assert result.exit_code == 0
    assert calls[0][-2:] == ["-o", str(outfile)]
