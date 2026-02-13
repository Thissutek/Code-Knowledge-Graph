"""
Tests for src/models.py — data model correctness.
"""
import json
from src.models import (
    CodeEntity, Repository, File, Module, Class, Function,
    Variable, Import, Interface, Parameter, Relationship,
    ParsedCodebase,
)


# ── CodeEntity ──────────────────────────────────────────────────────────────

class TestCodeEntity:
    def test_to_dict_excludes_none(self):
        e = CodeEntity(id="x", name="y")
        d = e.to_dict()
        assert d == {"id": "x", "name": "y"}

    def test_to_dict_excludes_private(self):
        e = CodeEntity(id="a", name="b")
        e._hidden = "secret"
        d = e.to_dict()
        assert "_hidden" not in d


# ── Repository ──────────────────────────────────────────────────────────────

class TestRepository:
    def test_to_dict_iso_datetime(self):
        from datetime import datetime
        dt = datetime(2025, 1, 15, 12, 30, 0)
        r = Repository(id="r1", name="repo", last_indexed=dt)
        d = r.to_dict()
        assert d["lastIndexed"] == "2025-01-15T12:30:00"

    def test_to_dict_no_datetime(self):
        r = Repository(id="r1", name="repo")
        d = r.to_dict()
        assert "lastIndexed" not in d


# ── File ────────────────────────────────────────────────────────────────────

class TestFile:
    def test_to_dict_renames_fields(self):
        f = File(id="f1", name="main.py", lines_of_code=100, content_hash="abc")
        d = f.to_dict()
        assert d["linesOfCode"] == 100
        assert d["hash"] == "abc"


# ── Class ───────────────────────────────────────────────────────────────────

class TestClass:
    def test_default_language_type(self):
        c = Class(id="c1", name="Foo")
        assert c.language_type == "class"

    def test_language_type_serialized(self):
        c = Class(id="c1", name="Foo", language_type="struct")
        d = c.to_dict()
        assert d["languageType"] == "struct"

    def test_all_language_type_values(self):
        for lt in ("class", "struct", "enum", "trait", "interface"):
            c = Class(id="c", name="X", language_type=lt)
            assert c.language_type == lt


# ── Function ────────────────────────────────────────────────────────────────

class TestFunction:
    def test_parameters_serialized_as_json_string(self):
        f = Function(
            id="f1", name="fn",
            parameters=[Parameter(name="x", type_annotation="int")],
        )
        d = f.to_dict()
        params = json.loads(d["parameters"])
        assert params[0]["name"] == "x"
        assert params[0]["type"] == "int"

    def test_default_visibility_public(self):
        f = Function(id="f1", name="fn")
        assert f.visibility == "public"


# ── Variable ────────────────────────────────────────────────────────────────

class TestVariable:
    def test_constant_flag(self):
        v = Variable(id="v1", name="MAX", is_constant=True)
        d = v.to_dict()
        assert d["isConstant"] is True


# ── Relationship ────────────────────────────────────────────────────────────

class TestRelationship:
    def test_to_dict_includes_props(self):
        r = Relationship(
            rel_type="CALLS", source_id="a", target_id="b",
            properties={"line": 42},
        )
        d = r.to_dict()
        assert d["type"] == "CALLS"
        assert d["sourceId"] == "a"
        assert d["targetId"] == "b"
        assert d["line"] == 42


# ── ParsedCodebase ──────────────────────────────────────────────────────────

class TestParsedCodebase:
    def test_add_relationship(self):
        repo = Repository(id="r", name="r")
        cb = ParsedCodebase(repository=repo)
        cb.add_relationship("FOO", "a", "b", extra="val")
        assert len(cb.relationships) == 1
        assert cb.relationships[0].rel_type == "FOO"
        assert cb.relationships[0].properties == {"extra": "val"}

    def test_get_stats_counts(self):
        repo = Repository(id="r", name="r")
        cb = ParsedCodebase(repository=repo)
        cb.files.append(File(id="f", name="f"))
        cb.classes.append(Class(id="c", name="C"))
        stats = cb.get_stats()
        assert stats["files"] == 1
        assert stats["classes"] == 1
        assert stats["functions"] == 0
