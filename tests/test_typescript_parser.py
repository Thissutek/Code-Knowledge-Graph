"""
Tests for the TypeScript/JavaScript tree-sitter parser.
"""
from pathlib import Path

from src.parsers.typescript_parser import TypeScriptLanguageParser
from tests.conftest import SAMPLE_TYPESCRIPT


def _parse(code: str, filename: str = "test.ts"):
    parser = TypeScriptLanguageParser()
    return parser.parse_file(Path(filename), code)


# ── Config / registration ───────────────────────────────────────────────────

class TestTypeScriptConfig:
    def test_extensions(self):
        p = TypeScriptLanguageParser()
        exts = p.config.extensions
        for e in (".ts", ".tsx", ".js", ".jsx"):
            assert e in exts

    def test_can_parse_ts(self):
        p = TypeScriptLanguageParser()
        assert p.can_parse(Path("app.ts"))
        assert p.can_parse(Path("component.tsx"))
        assert p.can_parse(Path("index.js"))
        assert p.can_parse(Path("App.jsx"))
        assert not p.can_parse(Path("main.py"))


# ── Classes ─────────────────────────────────────────────────────────────────

class TestTypeScriptClasses:
    def test_class_detected(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        names = [c.name for c in r["classes"]]
        assert "HttpClient" in names

    def test_class_extends(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        hc = next(c for c in r["classes"] if c.name == "HttpClient")
        assert "EventEmitter" in hc.base_classes

    def test_class_start_end_lines(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        hc = next(c for c in r["classes"] if c.name == "HttpClient")
        assert hc.start_line > 0
        assert hc.end_line >= hc.start_line


# ── Enums ───────────────────────────────────────────────────────────────────

class TestTypeScriptEnums:
    def test_enum_detected_as_class(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        enums = [c for c in r["classes"] if c.language_type == "enum"]
        names = [e.name for e in enums]
        assert "LogLevel" in names


# ── Functions ───────────────────────────────────────────────────────────────

class TestTypeScriptFunctions:
    def test_regular_function(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        names = [f.name for f in r["functions"]]
        assert "add" in names

    def test_arrow_function_captured(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        names = [f.name for f in r["functions"]]
        assert "greet" in names

    def test_method_is_method(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        fetch = next(f for f in r["functions"] if f.name == "fetch")
        assert fetch.is_method is True

    def test_static_method(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        create = next(f for f in r["functions"] if f.name == "create")
        assert create.is_static is True

    def test_async_detected(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        fetch = next(f for f in r["functions"] if f.name == "fetch")
        assert fetch.is_async is True

    def test_constructor_captured(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        names = [f.name for f in r["functions"]]
        assert "constructor" in names

    def test_parameters(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        add = next(f for f in r["functions"] if f.name == "add")
        assert len(add.parameters) == 2
        assert add.parameters[0].name == "a"


# ── Interfaces ──────────────────────────────────────────────────────────────

class TestTypeScriptInterfaces:
    def test_interface_detected(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        ifaces = r.get("interfaces", [])
        names = [i.name for i in ifaces]
        assert "Fetchable" in names

    def test_interface_methods(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        ifaces = r.get("interfaces", [])
        fetchable = next(i for i in ifaces if i.name == "Fetchable")
        assert "fetch" in fetchable.methods


# ── Imports ─────────────────────────────────────────────────────────────────

class TestTypeScriptImports:
    def test_named_import(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        sources = [i.source for i in r["imports"]]
        assert "events" in sources

    def test_default_import(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        sources = [i.source for i in r["imports"]]
        assert "axios" in sources

    def test_import_is_external(self):
        code = 'import { foo } from "./local";\nimport bar from "external";\n'
        r = _parse(code)
        local = next(i for i in r["imports"] if i.source == "./local")
        external = next(i for i in r["imports"] if i.source == "external")
        assert local.is_external is False
        assert external.is_external is True


# ── Relationships ───────────────────────────────────────────────────────────

class TestTypeScriptRelationships:
    def test_has_method_relationships(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        has_methods = [rel for rel in r["relationships"] if rel.rel_type == "HAS_METHOD"]
        assert len(has_methods) > 0

    def test_implements_relationship(self):
        r = _parse(SAMPLE_TYPESCRIPT)
        impl = [rel for rel in r["relationships"] if rel.rel_type == "IMPLEMENTS"]
        assert any("Fetchable" in r.target_id for r in impl)


# ── TSX / JSX variant ──────────────────────────────────────────────────────

class TestTSXParsing:
    def test_tsx_parses_jsx_syntax(self):
        tsx_code = (
            'import React from "react";\n'
            "function App(): JSX.Element {\n"
            "  return <div>Hello</div>;\n"
            "}\n"
        )
        r = _parse(tsx_code, "App.tsx")
        names = [f.name for f in r["functions"]]
        assert "App" in names

    def test_jsx_file(self):
        jsx_code = (
            'import React from "react";\n'
            "const Btn = () => <button>Click</button>;\n"
        )
        r = _parse(jsx_code, "Btn.jsx")
        names = [f.name for f in r["functions"]]
        assert "Btn" in names
