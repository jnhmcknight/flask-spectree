import json
import subprocess
import sys
import typing as t

import click
from flask import Flask
from flask.cli import AppGroup
from spectree import SpecTree as _SpecTree

from .flatten import flatten


class FlaskSpecTree(_SpecTree):
    """Thin Flask-aware wrapper around spectree.SpecTree.

    Defaults the backend to "flask" and supports the app-factory pattern
    via register(app) rather than requiring the app at construction time.
    """

    cli: AppGroup = None  # type: ignore

    def __init__(
        self, backend_name: str = "flask", app: Flask | None = None, **kwargs
    ):
        super().__init__(backend_name=backend_name, **kwargs)
        if app:
            self.init_app(app)

    def register(self, app: Flask) -> None:
        self.init_app(app)

    def init_app(self, app: Flask) -> None:
        if title := app.config.get("SPECTREE_TITLE"):
            self.config.title = title

        super().register(app)

        self.setup_cli()
        app.cli.add_command(self.cli)

        app.extensions["spectree"] = self

    def setup_cli(self) -> None:

        if self.cli is None:
            self.cli = AppGroup("spec", help="Interact with OpenAPI spec")

        @self.cli.command("export")
        @click.option(
            "--format",
            "format_",
            help="Which format to output the schema in",
            type=click.Choice(["json", "ts", "raw"]),
            default="json",
        )
        @click.option(
            "--flat",
            is_flag=True,
            help="Flatten the JSON or TS output, to reduce nested schema duplication",
            default=False,
        )
        @click.option(
            "-o",
            "--output-file",
            help="Output file name",
            default="-",
            type=click.File("w", encoding="utf-8"),
        )
        def export(format_: str, flat: bool, output_file: t.TextIO):
            """Generate the OpenAPI spec."""
            data = self.spec

            if format_ == "raw":
                click.echo(data, file=output_file)
                return

            maybe_flattened = flatten(data) if flat else data

            if format_ == "ts":
                cmd = [
                    "npx",
                    "openapi-typescript",
                    "--alphabetize",
                    "--root-types",
                    "--root-types-no-schema-prefix",
                    "--dedupe-enums",
                    "--enums",
                ]
                if output_file.name != "<stdout>":
                    cmd.extend(
                        [
                            "-o",
                            output_file.name,
                        ]
                    )

                try:
                    result = subprocess.run(
                        cmd,
                        input=json.dumps(maybe_flattened),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                except FileNotFoundError as exc:
                    raise click.ClickException(
                        "npx was not found; Node.js is required for TS output"
                    ) from exc

                if result.stdout:
                    click.echo(result.stdout)
                if result.stderr:
                    click.echo(result.stderr, file=sys.stderr)
                if result.returncode:
                    raise click.ClickException(
                        f"openapi-typescript exited with status {result.returncode}"
                    )
                return

            output_file.write(json.dumps(maybe_flattened, indent=2))

        @self.cli.command("flatten")
        @click.option(
            "-i", "--input-file", default="-", type=click.File("r", encoding="utf-8")
        )
        @click.option(
            "-o", "--output-file", default="-", type=click.File("w", encoding="utf-8")
        )
        def flat(input_file: t.TextIO, output_file: t.TextIO):
            """Flatten an OpenAPI JSON spec by promoting nested component schemas to root level.

            The input and output files default to stdin and stdout.
            """
            spec = json.load(input_file)
            flat = flatten(spec)
            json.dump(flat, output_file, indent=2)
