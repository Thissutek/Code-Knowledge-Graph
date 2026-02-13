"""
Tests for the Go tree-sitter parser.
"""
from pathlib import Path

from src.parsers.go_parser import GoLanguageParser
from tests.conftest import SAMPLE_GO


def _parse(code: str, filename: str = "main.go"):
    parser = GoLanguageParser()
    return parser.parse_file(Path(filename), code)


# ── Config ──────────────────────────────────────────────────────────────────

class TestGoConfig:
    def test_extensions(self):
        p = GoLanguageParser()
        assert ".go" in p.config.extensions

    def test_can_parse(self):
        p = GoLanguageParser()
        assert p.can_parse(Path("server.go"))
        assert not p.can_parse(Path("server.rs"))


# ── Structs ─────────────────────────────────────────────────────────────────

class TestGoStructs:
    def test_struct_detected(self):
        r = _parse(SAMPLE_GO)
        names = [c.name for c in r["classes"]]
        assert "Config" in names
        assert "Server" in names

    def test_struct_language_type(self):
        r = _parse(SAMPLE_GO)
        cfg = next(c for c in r["classes"] if c.name == "Config")
        assert cfg.language_type == "struct"

    def test_embedded_struct_as_base_class(self):
        r = _parse(SAMPLE_GO)
        srv = next(c for c in r["classes"] if c.name == "Server")
        assert "Config" in srv.base_classes


# ── Interfaces ──────────────────────────────────────────────────────────────

class TestGoInterfaces:
    def test_interface_detected(self):
        r = _parse(SAMPLE_GO)
        ifaces = r.get("interfaces", [])
        names = [i.name for i in ifaces]
        assert "Handler" in names

    def test_interface_methods(self):
        r = _parse(SAMPLE_GO)
        ifaces = r.get("interfaces", [])
        handler = next(i for i in ifaces if i.name == "Handler")
        assert "Handle" in handler.methods


# ── Functions ───────────────────────────────────────────────────────────────

class TestGoFunctions:
    def test_free_function(self):
        r = _parse(SAMPLE_GO)
        names = [f.name for f in r["functions"]]
        assert "NewServer" in names
        assert "main" in names

    def test_method_with_receiver(self):
        r = _parse(SAMPLE_GO)
        start = next(f for f in r["functions"] if f.name == "Start")
        assert start.is_method is True

    def test_visibility_uppercase_public(self):
        r = _parse(SAMPLE_GO)
        ns = next(f for f in r["functions"] if f.name == "NewServer")
        assert ns.visibility == "public"
        main_fn = next(f for f in r["functions"] if f.name == "main")
        assert main_fn.visibility == "private"

    def test_parameters(self):
        r = _parse(SAMPLE_GO)
        ns = next(f for f in r["functions"] if f.name == "NewServer")
        assert len(ns.parameters) >= 2
        param_names = [p.name for p in ns.parameters]
        assert "host" in param_names
        assert "port" in param_names

    def test_return_type(self):
        r = _parse(SAMPLE_GO)
        ns = next(f for f in r["functions"] if f.name == "NewServer")
        assert ns.return_type is not None


# ── Variables ───────────────────────────────────────────────────────────────

class TestGoVariables:
    def test_const(self):
        r = _parse(SAMPLE_GO)
        consts = [v for v in r["variables"] if v.is_constant]
        names = [v.name for v in consts]
        assert "MaxConnections" in names

    def test_var(self):
        r = _parse(SAMPLE_GO)
        names = [v.name for v in r["variables"]]
        assert "DefaultTimeout" in names


# ── Imports ─────────────────────────────────────────────────────────────────

class TestGoImports:
    def test_imports(self):
        r = _parse(SAMPLE_GO)
        sources = [i.source for i in r["imports"]]
        assert "fmt" in sources
        assert "os" in sources
        assert "sync" in sources


# ── Relationships ───────────────────────────────────────────────────────────

class TestGoRelationships:
    def test_has_method(self):
        r = _parse(SAMPLE_GO)
        hm = [rel for rel in r["relationships"] if rel.rel_type == "HAS_METHOD"]
        # Start and Stop should be methods of Server
        target_names = [rel.target_id for rel in hm]
        assert any("Start" in t for t in target_names)
        assert any("Stop" in t for t in target_names)


# ── Function calls ─────────────────────────────────────────────────────────

class TestGoFunctionCalls:
    def test_main_calls_extracted(self):
        r = _parse(SAMPLE_GO)
        fc = r.get("function_calls", {})
        main_calls = {k: v for k, v in fc.items() if k.endswith(":main")}
        assert len(main_calls) > 0
        all_names = [name for calls in main_calls.values() for name, _ in calls]
        assert "NewServer" in all_names

    def test_method_calls_extracted(self):
        r = _parse(SAMPLE_GO)
        fc = r.get("function_calls", {})
        start_calls = {k: v for k, v in fc.items() if "Start" in k}
        assert len(start_calls) > 0
        all_names = [name for calls in start_calls.values() for name, _ in calls]
        assert "Lock" in all_names
