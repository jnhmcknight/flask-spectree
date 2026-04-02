"""
Flatten an OpenAPI 3.x JSON spec by promoting nested component schemas to root level.

Pydantic v2 generates schema names like:
  - "AccessoryDetailOut.90e892a"             (top-level with model hash)
  - "AccessoryDetailOut.90e892a.UserNested"  (child schema)

This script:
  1. Strips hash suffixes    ->  AccessoryDetailOut.90e892a  =>  AccessoryDetailOut
  2. Promotes child schemas  ->  Parent.hash.Child           =>  Child
  3. Two-pass deduplication:
       Pass 1 - collapse schemas with the same short name that are already
                identical (e.g. all 12 UserNested copies)
       Pass 2 - after normalising internal $refs, collapse schemas whose
                content is now the same (e.g. StorageNested variants that
                only differed via their ImageNested/UserNested refs)
  4. Disambiguates genuinely different schemas (Parent_Child naming)
  5. Rewrites every $ref in the document to use the new canonical names

Usage:
  python flatten.py [INPUT_FILE] [OUTPUT_FILE]

Defaults: openapi.json -> openapi.flat.json
"""

import json
import re
from collections import defaultdict
from copy import deepcopy

HASH_RE = re.compile(r"\.[0-9a-f]{7}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_name(name: str) -> str:
    """
    Desired short name for a schema:
      Parent.hash.Child  ->  Child
      Parent.hash        ->  Parent
      Parent             ->  Parent
    """
    parts = name.split(".")
    if len(parts) == 3:
        return parts[2]
    if len(parts) == 2:
        return parts[0]
    return name


def _parent_prefix(name: str) -> str | None:
    """Return the parent name for a 3-part schema, else None."""
    parts = name.split(".")
    if len(parts) == 3:
        return parts[0]
    return None


def _rewrite_refs_in(obj, rename: dict[str, str]):
    """Recursively rewrite all local $ref values using *rename* (mutates obj)."""
    if isinstance(obj, dict):
        if "$ref" in obj:
            ref = obj["$ref"]
            prefix = "#/components/schemas/"
            if ref.startswith(prefix):
                old = ref[len(prefix) :]
                obj["$ref"] = prefix + rename.get(old, old)
        for v in obj.values():
            _rewrite_refs_in(v, rename)
    elif isinstance(obj, list):
        for item in obj:
            _rewrite_refs_in(item, rename)


def _content_key(schema: dict) -> str:
    return json.dumps(schema, sort_keys=True)


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------


def build_rename_map(schemas: dict) -> dict[str, str]:
    """
    Two-pass algorithm that returns {old_name: canonical_name}.

    Pass 1: group by short name; identical schemas share one canonical name.
            Non-identical groups are disambiguated with Parent_Child.
    Pass 2: apply the pass-1 map to $refs *inside* each schema, then re-check
            for newly-identical schemas and merge them.
    """

    # --- pass 1 -----------------------------------------------------------
    # Priority: 2-part names (top-level with hash) beat 3-part names (nested)
    # when they collide on the same short name.
    by_short: dict[str, list[str]] = defaultdict(list)
    for name in schemas:
        by_short[_short_name(name)].append(name)

    rename1: dict[str, str] = {}

    def _assign(originals: list[str], target: str):
        for orig in originals:
            rename1[orig] = target

    for short, originals in by_short.items():
        if len(originals) == 1:
            _assign(originals, short)
            continue

        # Split by content
        by_content: dict[str, list[str]] = defaultdict(list)
        for orig in originals:
            by_content[_content_key(schemas[orig])].append(orig)

        if len(by_content) == 1:
            # All identical → one canonical name
            _assign(originals, short)
            continue

        # Multiple distinct schemas want the same short name.
        # Prefer the 2-part (top-level) schema for the undecorated name.
        two_part = [n for n in originals if len(n.split(".")) == 2]
        three_part = [n for n in originals if len(n.split(".")) == 3]

        if two_part:
            # The 2-part schema keeps the short name (if all 2-part are identical)
            tp_contents = {_content_key(schemas[n]) for n in two_part}
            if len(tp_contents) == 1:
                _assign(two_part, short)
            else:
                # Even multiple 2-part schemas differ; disambiguate all
                three_part = originals
                two_part = []

        # Disambiguate 3-part schemas that couldn't get the bare short name
        remaining = three_part
        if remaining:
            # Group remaining by content
            rem_by_content: dict[str, list[str]] = defaultdict(list)
            for orig in remaining:
                rem_by_content[_content_key(schemas[orig])].append(orig)

            used: set[str] = set(rename1.values())
            for group in rem_by_content.values():
                rep = group[0]
                parent = _parent_prefix(rep) or rep
                candidate = f"{parent}_{short}"
                # avoid collision with already-assigned names
                suffix = 2
                base = candidate
                while candidate in used:
                    candidate = f"{base}_{suffix}"
                    suffix += 1
                used.add(candidate)
                _assign(group, candidate)

    # --- pass 2: normalise $refs inside schemas, then re-deduplicate -------
    # Clone schemas and rewrite their internal refs using the pass-1 map.
    normalised: dict[str, dict] = {}
    for old_name, schema in schemas.items():
        s = deepcopy(schema)
        _rewrite_refs_in(s, rename1)
        normalised[rename1[old_name]] = s  # keyed by pass-1 canonical name

    # For canonical names that now have identical content, merge them.
    # Collect all original → pass-1 mappings grouped by pass-1 name.
    by_canonical: dict[str, list[str]] = defaultdict(list)
    for orig, canon in rename1.items():
        by_canonical[canon].append(orig)

    # Build a map: pass-1 canonical name → original short name (before disambiguation)
    canon_to_short: dict[str, str] = {}
    for orig, canon in rename1.items():
        canon_to_short[canon] = _short_name(orig)

    # Find canonical names whose normalised content is the same as another.
    # Collect all content groups first, then pick the best name for each.
    content_to_canons: dict[str, list[str]] = defaultdict(list)
    for canon, norm_schema in normalised.items():
        ck = _content_key(norm_schema)
        content_to_canons[ck].append(canon)

    def _name_quality(n: str) -> tuple:
        # Prefer: fewest underscores, then shortest, then alphabetical
        return (n.count("_"), len(n), n)

    content_to_final: dict[str, str] = {}
    for ck, canons in content_to_canons.items():
        # If all schemas in this group share the same original short name and
        # that short name is NOT already claimed by a different content group,
        # reclaim the bare short name (e.g. StorageNested, not AmmoDetailOut_StorageNested)
        short_names = {canon_to_short[c] for c in canons}
        if len(short_names) == 1:
            bare = next(iter(short_names))
            # Only use the bare name if it's not claimed by a *different* content group
            # (i.e., either it's free or all its claimants are in this group)
            claimants = [c for c in normalised if canon_to_short.get(c) == bare]
            if set(claimants) == set(canons):
                content_to_final[ck] = bare
                continue
        # Fall back: pick the cleanest name already in the candidate list
        content_to_final[ck] = min(canons, key=_name_quality)

    canon_rename: dict[str, str] = {
        canon: content_to_final[_content_key(norm_schema)]
        for canon, norm_schema in normalised.items()
    }

    # Compose pass-1 and pass-2 renames into a single map
    rename_final: dict[str, str] = {
        orig: canon_rename[pass1] for orig, pass1 in rename1.items()
    }

    return rename_final


def rebuild_schemas(schemas: dict, rename: dict[str, str]) -> dict:
    """
    Return a new schemas dict keyed by canonical names (deduplicated).
    Each schema's internal $refs are already rewritten by the caller.
    """
    new_schemas: dict = {}
    for old_name, schema in schemas.items():
        new_name = rename[old_name]
        if new_name not in new_schemas:
            new_schemas[new_name] = schema
    return dict(sorted(new_schemas.items()))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def flatten(spec: dict, *, debug: bool = False) -> dict:
    spec = deepcopy(spec)
    schemas = spec.get("components", {}).get("schemas", {})

    if not schemas:
        if debug:
            print(  # noqa T201
                "No schemas found under components.schemas - nothing to do."
            )
        return spec

    rename = build_rename_map(schemas)

    # Stats
    changed = {k: v for k, v in rename.items() if k != v}
    unique_after = len(set(rename.values()))
    if debug:
        print(f"Schemas before: {len(schemas)}")  # noqa T201
        print(f"Schemas renamed/merged: {len(changed)}")  # noqa T201
        print(f"Schemas after:  {unique_after}")  # noqa T201
        print()  # noqa T201

    if changed and debug:
        col = max(len(k) for k in changed)
        print(f"{'Old name':<{col}}  ->  New name")  # noqa T201
        print("-" * (col + 16))  # noqa T201
        for old, new in sorted(changed.items()):
            print(f"  {old:<{col}}  ->  {new}")  # noqa T201

    # Rewrite $refs in the full document (paths, request bodies, responses, …)
    _rewrite_refs_in(spec, rename)

    # Rebuild components.schemas: rewrite internal refs, then deduplicate
    new_schemas: dict = {}
    for old_name, schema in schemas.items():
        new_name = rename[old_name]
        if new_name not in new_schemas:
            s = deepcopy(schema)
            _rewrite_refs_in(s, rename)
            new_schemas[new_name] = s

    spec["components"]["schemas"] = dict(sorted(new_schemas.items()))
    return spec
