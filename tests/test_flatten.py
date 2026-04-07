"""Tests for flask_spectree.flatten — deduplication logic."""

from flask_spectree.flatten import (
    _parent_prefix,
    _rewrite_refs_in,
    _short_name,
    build_rename_map,
    flatten,
    rebuild_schemas,
)


def _make_spec(schemas: dict) -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Test", "version": "0.1.0"},
        "components": {"schemas": schemas},
    }


# ---------------------------------------------------------------------------
# _short_name
# ---------------------------------------------------------------------------


def test_short_name_three_part():
    assert _short_name("Parent.abc1234.Child") == "Child"


def test_short_name_two_part():
    assert _short_name("Parent.abc1234") == "Parent"


def test_short_name_one_part():
    assert _short_name("Simple") == "Simple"


# ---------------------------------------------------------------------------
# _parent_prefix
# ---------------------------------------------------------------------------


def test_parent_prefix_three_part():
    assert _parent_prefix("Parent.abc1234.Child") == "Parent"


def test_parent_prefix_two_part():
    assert _parent_prefix("Parent.abc1234") is None


def test_parent_prefix_one_part():
    assert _parent_prefix("Simple") is None


# ---------------------------------------------------------------------------
# _rewrite_refs_in
# ---------------------------------------------------------------------------


def test_rewrite_refs_in_rewrites_schema_ref():
    obj = {"$ref": "#/components/schemas/OldName"}
    _rewrite_refs_in(obj, {"OldName": "NewName"})
    assert obj["$ref"] == "#/components/schemas/NewName"


def test_rewrite_refs_in_unknown_name_unchanged():
    obj = {"$ref": "#/components/schemas/Unknown"}
    _rewrite_refs_in(obj, {"OtherName": "NewName"})
    assert obj["$ref"] == "#/components/schemas/Unknown"


def test_rewrite_refs_in_non_schema_ref_unchanged():
    obj = {"$ref": "#/other/path/Thing"}
    _rewrite_refs_in(obj, {"Thing": "Other"})
    assert obj["$ref"] == "#/other/path/Thing"


def test_rewrite_refs_in_nested_dict():
    obj = {"properties": {"x": {"$ref": "#/components/schemas/Foo"}}}
    _rewrite_refs_in(obj, {"Foo": "Bar"})
    assert obj["properties"]["x"]["$ref"] == "#/components/schemas/Bar"


def test_rewrite_refs_in_list():
    obj = [{"$ref": "#/components/schemas/Foo"}, {"other": "value"}]
    _rewrite_refs_in(obj, {"Foo": "Bar"})
    assert obj[0]["$ref"] == "#/components/schemas/Bar"


# ---------------------------------------------------------------------------
# flatten — early return / no-op cases
# ---------------------------------------------------------------------------


def test_flatten_no_components_key():
    spec = {"openapi": "3.1.0", "info": {"title": "T", "version": "0.1.0"}}
    assert flatten(spec) == spec


def test_flatten_empty_schemas():
    spec = _make_spec({})
    assert flatten(spec) == spec


def test_flatten_debug_no_schemas_does_not_raise(capsys):
    spec = _make_spec({})
    flatten(spec, debug=True)
    captured = capsys.readouterr()
    assert "nothing to do" in captured.out


# ---------------------------------------------------------------------------
# flatten — basic rename cases
# ---------------------------------------------------------------------------


def test_flatten_strips_hash_from_two_part_name():
    spec = _make_spec({"Foo.abc1234": {"type": "object"}})
    schemas = flatten(spec)["components"]["schemas"]
    assert "Foo" in schemas
    assert "Foo.abc1234" not in schemas


def test_flatten_promotes_three_part_nested_schema():
    spec = _make_spec({"Parent.abc1234.Child": {"type": "string"}})
    schemas = flatten(spec)["components"]["schemas"]
    assert "Child" in schemas
    assert "Parent.abc1234.Child" not in schemas


def test_flatten_does_not_mutate_input():
    spec = _make_spec({"Foo.abc1234": {"type": "object"}})
    original_keys = list(spec["components"]["schemas"].keys())
    flatten(spec)
    assert list(spec["components"]["schemas"].keys()) == original_keys


def test_flatten_rewrites_refs_throughout_document():
    spec = _make_spec({"Foo.abc1234": {"type": "object"}})
    spec["paths"] = {
        "/foo": {
            "get": {
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/Foo.abc1234"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    result = flatten(spec)
    ref = (
        result["paths"]["/foo"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
    )
    assert ref == "#/components/schemas/Foo"


def test_flatten_debug_prints_stats(capsys):
    spec = _make_spec(
        {
            "Foo.abc1234": {"type": "object"},
            "Bar.def5678.Foo": {"type": "string"},
        }
    )
    flatten(spec, debug=True)
    captured = capsys.readouterr()
    assert "Schemas before:" in captured.out
    assert "Schemas after:" in captured.out


# ---------------------------------------------------------------------------
# Pass-1: multiple originals mapping to the same short name
# ---------------------------------------------------------------------------


def test_flatten_merges_identical_schemas_sharing_short_name():
    """Two schemas with the same short name and identical content collapse to one."""
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    spec = _make_spec(
        {
            "Foo.aaa1111": schema,
            "Bar.bbb2222.Foo": schema,
        }
    )
    schemas = flatten(spec)["components"]["schemas"]
    assert list(schemas.keys()) == ["Foo"]


def test_flatten_two_part_wins_short_name_over_three_part():
    """When a 2-part and a 3-part schema share a short name but differ,
    the 2-part keeps the bare short name; the 3-part gets Parent_Child."""
    spec = _make_spec(
        {
            "Foo.abc1234": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
            },
            "Bar.def5678.Foo": {
                "type": "object",
                "properties": {"b": {"type": "integer"}},
            },
        }
    )
    schemas = flatten(spec)["components"]["schemas"]
    assert "Foo" in schemas
    assert schemas["Foo"]["properties"]["a"]["type"] == "string"
    assert "Bar_Foo" in schemas
    assert schemas["Bar_Foo"]["properties"]["b"]["type"] == "integer"


def test_flatten_conflicting_two_part_schemas_both_disambiguated():
    """Two distinct 2-part schemas sharing a short name are both renamed
    with Parent_short disambiguation (neither can claim the bare name)."""
    spec = _make_spec(
        {
            "Foo.abc1234": {"type": "object", "properties": {"a": {"type": "string"}}},
            "Foo.def5678": {
                "type": "object",
                "properties": {"b": {"type": "integer"}},
            },
        }
    )
    result = flatten(spec)
    schemas = result["components"]["schemas"]
    # Neither schema keeps the bare "Foo" — both are disambiguated
    assert "Foo" not in schemas
    assert len(schemas) == 2


# ---------------------------------------------------------------------------
# Pass-2: schemas that differ only in $refs collapse after ref normalisation
# ---------------------------------------------------------------------------


def test_flatten_pass2_reclaims_bare_name_for_same_short_name():
    """Two 2-part schemas share a short name, conflict in pass 1, but become
    identical in pass 2 after their child refs normalise.  The bare short name
    should be reclaimed rather than keeping the mangled disambiguation."""
    child = {"type": "string"}
    spec = _make_spec(
        {
            "Child.aaa1111": child,
            "Child.bbb2222": child,
            "Storage.ccc3333": {
                "type": "object",
                "properties": {
                    "child": {"$ref": "#/components/schemas/Child.aaa1111"}
                },
            },
            "Storage.ddd4444": {
                "type": "object",
                "properties": {
                    "child": {"$ref": "#/components/schemas/Child.bbb2222"}
                },
            },
        }
    )
    schemas = flatten(spec)["components"]["schemas"]
    assert "Child" in schemas
    # Both Storage variants collapse to the bare "Storage" (not "Storage.xxx_Storage")
    assert "Storage" in schemas
    assert len(schemas) == 2


def test_flatten_pass2_fallback_name_quality_winner():
    """Schemas with *different* short names that become identical after pass-2
    ref normalisation fall back to the _name_quality winner: fewest underscores,
    then shortest, then alphabetical."""
    child = {"type": "string"}
    spec = _make_spec(
        {
            "Child.aaa1111": child,
            "Child.bbb2222": child,
            # "Cat" and "Dog" differ only in which Child variant they reference;
            # after normalisation both refs become "Child" and the schemas are equal.
            "Cat.ccc3333": {
                "type": "object",
                "properties": {
                    "child": {"$ref": "#/components/schemas/Child.aaa1111"}
                },
            },
            "Dog.ddd4444": {
                "type": "object",
                "properties": {
                    "child": {"$ref": "#/components/schemas/Child.bbb2222"}
                },
            },
        }
    )
    schemas = flatten(spec)["components"]["schemas"]
    # Both collapse; "Cat" wins over "Dog" (equal length, alphabetically first)
    assert "Child" in schemas
    assert "Cat" in schemas
    assert "Dog" not in schemas
    assert len(schemas) == 2


# ---------------------------------------------------------------------------
# rebuild_schemas
# ---------------------------------------------------------------------------


def test_rebuild_schemas_basic():
    schemas = {"Foo.abc1234": {"type": "object"}}
    rename = {"Foo.abc1234": "Foo"}
    assert rebuild_schemas(schemas, rename) == {"Foo": {"type": "object"}}


def test_rebuild_schemas_deduplicates():
    schema = {"type": "object"}
    schemas = {"Foo.aaa1111": schema, "Bar.bbb2222.Foo": schema}
    rename = {"Foo.aaa1111": "Foo", "Bar.bbb2222.Foo": "Foo"}
    result = rebuild_schemas(schemas, rename)
    assert list(result.keys()) == ["Foo"]


def test_rebuild_schemas_output_is_sorted():
    schemas = {
        "Zebra.aaa1111": {"type": "string"},
        "Apple.bbb2222": {"type": "integer"},
    }
    rename = {"Zebra.aaa1111": "Zebra", "Apple.bbb2222": "Apple"}
    result = rebuild_schemas(schemas, rename)
    assert list(result.keys()) == ["Apple", "Zebra"]


# ---------------------------------------------------------------------------
# build_rename_map — direct unit tests
# ---------------------------------------------------------------------------


def test_build_rename_map_single_schema():
    schemas = {"Foo.abc1234": {"type": "object"}}
    assert build_rename_map(schemas) == {"Foo.abc1234": "Foo"}


def test_build_rename_map_identical_schemas_share_canonical_name():
    schema = {"type": "object"}
    schemas = {"Foo.aaa1111": schema, "Bar.bbb2222.Foo": schema}
    result = build_rename_map(schemas)
    assert result["Foo.aaa1111"] == "Foo"
    assert result["Bar.bbb2222.Foo"] == "Foo"


def test_build_rename_map_collision_avoidance():
    """Two 3-part schemas with the same parent prefix and the same short name
    but different content: the second one can't claim 'Parent_Child' because
    the first already took it, so the suffix counter kicks in → 'Parent_Child_2'."""
    schemas = {
        "Parent.aaa1111.Nested": {"type": "string"},   # → Parent_Nested
        "Parent.bbb2222.Nested": {"type": "integer"},  # → Parent_Nested_2 (collision)
        "Other.ccc3333.Nested": {"type": "boolean"},   # → Other_Nested
    }
    result = build_rename_map(schemas)
    values = set(result.values())
    # All three must end up with distinct names
    assert len(values) == 3
    # The two Parent variants must be disambiguated sequentially
    assert "Parent_Nested" in values
    assert "Parent_Nested_2" in values
    assert "Other_Nested" in values
