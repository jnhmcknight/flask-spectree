# Flask-Spectree

A thin Flask wrapper around [spectree](https://github.com/0b01001001/spectree) that adds useful CLI tools for exporting and flattening OpenAPI specs while not affecting any other aspect of Spectree's normal usage patterns.

## Installation

```bash
pip install flask-spectree
```

Requires Flask >= 3.0 and spectree >= 1.3.

## Usage

### Direct initialization

```python
from flask import Flask
from flask_spectree import FlaskSpecTree

app = Flask(__name__)
spec = FlaskSpecTree(app)
```

### App-factory pattern

```python
from flask_spectree import FlaskSpecTree

spec = FlaskSpecTree()

def create_app():
    app = Flask(__name__)
    spec.init_app(app)
    return app
```

After registration, the OpenAPI spec is served at `/apidoc/openapi.json`.

### Configuration

| Config key        | Description               |
|-------------------|---------------------------|
| `SPECTREE_TITLE`  | Title shown in the spec   |

All other `spectree` options can be passed as keyword arguments to `FlaskSpecTree(...)`.

## CLI

After registering the extension, a `spec` command group is added to the Flask CLI.

### Export the spec

```bash
flask spec export [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--format [json\|ts\|raw]` | `json` | Output format |
| `--flat` | off | Flatten schema before output (reduces nested duplication) |
| `-o / --output-file` | stdout | Write output to a file |

**Examples:**

```bash
# Print JSON to stdout
flask spec export

# Write flattened JSON to a file
flask spec export --flat -o openapi.json

# Generate TypeScript types (requires `npx openapi-typescript`)
flask spec export --format ts -o src/api.d.ts
```

### Flatten a spec file

Promotes nested Pydantic v2 component schemas to root level, strips hash suffixes, and deduplicates identical schemas.

```bash
flask spec flatten [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `-i / --input-file` | stdin | Input OpenAPI JSON file |
| `-o / --output-file` | stdout | Output file |

**Examples:**

```bash
# Flatten from file to file
flask spec flatten -i openapi.json -o openapi.flat.json

# Pipe
cat openapi.json | flask spec flatten > openapi.flat.json
```

## Schema flattening

Pydantic v2 generates verbose schema names like `AccessoryDetailOut.90e892a` and `AccessoryDetailOut.90e892a.UserNested`. The flattener:

1. Strips hash suffixes (`AccessoryDetailOut.90e892a` → `AccessoryDetailOut`)
2. Promotes child schemas (`Parent.hash.Child` → `Child`)
3. Deduplicates identical schemas across two passes
4. Disambiguates genuinely different schemas with `Parent_Child` naming
5. Rewrites all `$ref` values throughout the document
