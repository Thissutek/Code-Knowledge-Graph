"""
Tests for the Rust tree-sitter parser.
"""
from pathlib import Path

from src.parsers.rust_parser import RustLanguageParser
from tests.conftest import SAMPLE_RUST


def _parse(code: str, filename: str = "lib.rs"):
    parser = RustLanguageParser()
    return parser.parse_file(Path(filename), code)


# ── Config ──────────────────────────────────────────────────────────────────

class TestRustConfig:
    def test_extensions(self):
        p = RustLanguageParser()
        assert ".rs" in p.config.extensions

    def test_can_parse(self):
        p = RustLanguageParser()
        assert p.can_parse(Path("lib.rs"))
        assert not p.can_parse(Path("main.go"))


# ── Structs ─────────────────────────────────────────────────────────────────

class TestRustStructs:
    def test_struct_detected(self):
        r = _parse(SAMPLE_RUST)
        names = [c.name for c in r["classes"]]
        assert "Cache" in names

    def test_struct_language_type(self):
        r = _parse(SAMPLE_RUST)
        cache = next(c for c in r["classes"] if c.name == "Cache")
        assert cache.language_type == "struct"


# ── Enums ───────────────────────────────────────────────────────────────────

class TestRustEnums:
    def test_enum_detected(self):
        r = _parse(SAMPLE_RUST)
        enums = [c for c in r["classes"] if c.language_type == "enum"]
        names = [e.name for e in enums]
        assert "CacheError" in names


# ── Traits ──────────────────────────────────────────────────────────────────

class TestRustTraits:
    def test_trait_detected(self):
        r = _parse(SAMPLE_RUST)
        ifaces = r.get("interfaces", [])
        names = [i.name for i in ifaces]
        assert "Storage" in names

    def test_trait_methods(self):
        r = _parse(SAMPLE_RUST)
        ifaces = r.get("interfaces", [])
        storage = next(i for i in ifaces if i.name == "Storage")
        assert "get" in storage.methods
        assert "set" in storage.methods


# ── Functions / impl blocks ─────────────────────────────────────────────────

class TestRustFunctions:
    def test_impl_methods(self):
        r = _parse(SAMPLE_RUST)
        names = [f.name for f in r["functions"]]
        assert "new" in names
        assert "len" in names

    def test_trait_impl_methods(self):
        r = _parse(SAMPLE_RUST)
        names = [f.name for f in r["functions"]]
        assert "get" in names
        assert "set" in names

    def test_pub_visibility(self):
        r = _parse(SAMPLE_RUST)
        new_fn = next(f for f in r["functions"] if f.name == "new")
        assert new_fn.visibility == "public"

    def test_self_parameter(self):
        r = _parse(SAMPLE_RUST)
        len_fn = next(f for f in r["functions"] if f.name == "len")
        param_names = [p.name for p in len_fn.parameters]
        assert any("self" in n for n in param_names)

    def test_return_type(self):
        r = _parse(SAMPLE_RUST)
        new_fn = next(f for f in r["functions"] if f.name == "new")
        assert new_fn.return_type is not None


# ── Variables ───────────────────────────────────────────────────────────────

class TestRustVariables:
    def test_const(self):
        r = _parse(SAMPLE_RUST)
        consts = [v for v in r["variables"] if v.is_constant]
        names = [v.name for v in consts]
        assert "MAX_CACHE_SIZE" in names


# ── Imports ─────────────────────────────────────────────────────────────────

class TestRustImports:
    def test_use_import(self):
        r = _parse(SAMPLE_RUST)
        names = [i.name for i in r["imports"]]
        assert "HashMap" in names

    def test_grouped_use(self):
        code = "use std::io::{self, Read, Write};\n"
        r = _parse(code)
        names = [i.name for i in r["imports"]]
        assert "Read" in names
        assert "Write" in names


# ── Relationships ───────────────────────────────────────────────────────────

class TestRustRelationships:
    def test_has_method(self):
        r = _parse(SAMPLE_RUST)
        hm = [rel for rel in r["relationships"] if rel.rel_type == "HAS_METHOD"]
        assert len(hm) > 0

    def test_implements_trait(self):
        r = _parse(SAMPLE_RUST)
        impl = [rel for rel in r["relationships"] if rel.rel_type == "IMPLEMENTS"]
        assert any("Storage" in rel.target_id for rel in impl)

    def test_display_impl(self):
        r = _parse(SAMPLE_RUST)
        impl = [rel for rel in r["relationships"] if rel.rel_type == "IMPLEMENTS"]
        # CacheError implements Display
        assert any("Display" in rel.target_id for rel in impl)
