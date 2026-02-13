"""
Tests for the language registry (src/languages.py).
Ensures all parsers are correctly registered and routable.
"""
from pathlib import Path

from src.languages import (
    LANGUAGE_PARSERS,
    get_parser_for_file,
    get_all_supported_extensions,
    PythonLanguageParser,
)
from src.parsers.typescript_parser import TypeScriptLanguageParser
from src.parsers.java_parser import JavaLanguageParser
from src.parsers.go_parser import GoLanguageParser
from src.parsers.rust_parser import RustLanguageParser
from src.parsers.cpp_parser import CppLanguageParser


# ── Registration ────────────────────────────────────────────────────────────

class TestRegistration:
    def test_python_registered(self):
        assert ".py" in LANGUAGE_PARSERS
        assert ".pyw" in LANGUAGE_PARSERS

    def test_typescript_registered(self):
        for ext in (".ts", ".tsx", ".js", ".jsx"):
            assert ext in LANGUAGE_PARSERS, f"{ext} not registered"

    def test_java_registered(self):
        assert ".java" in LANGUAGE_PARSERS

    def test_go_registered(self):
        assert ".go" in LANGUAGE_PARSERS

    def test_rust_registered(self):
        assert ".rs" in LANGUAGE_PARSERS

    def test_cpp_registered(self):
        for ext in (".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx"):
            assert ext in LANGUAGE_PARSERS, f"{ext} not registered"

    def test_total_extension_count(self):
        # Python(2) + TS(4) + Java(1) + Go(1) + Rust(1) + C/C++(7) = 16
        assert len(LANGUAGE_PARSERS) == 16


# ── get_parser_for_file ─────────────────────────────────────────────────────

class TestGetParserForFile:
    def test_python_routing(self):
        p = get_parser_for_file(Path("main.py"))
        assert isinstance(p, PythonLanguageParser)

    def test_typescript_routing(self):
        p = get_parser_for_file(Path("app.ts"))
        assert isinstance(p, TypeScriptLanguageParser)

    def test_tsx_routing(self):
        p = get_parser_for_file(Path("component.tsx"))
        assert isinstance(p, TypeScriptLanguageParser)

    def test_js_routing(self):
        p = get_parser_for_file(Path("index.js"))
        assert isinstance(p, TypeScriptLanguageParser)

    def test_java_routing(self):
        p = get_parser_for_file(Path("Main.java"))
        assert isinstance(p, JavaLanguageParser)

    def test_go_routing(self):
        p = get_parser_for_file(Path("main.go"))
        assert isinstance(p, GoLanguageParser)

    def test_rust_routing(self):
        p = get_parser_for_file(Path("lib.rs"))
        assert isinstance(p, RustLanguageParser)

    def test_cpp_routing(self):
        p = get_parser_for_file(Path("main.cpp"))
        assert isinstance(p, CppLanguageParser)

    def test_c_routing(self):
        p = get_parser_for_file(Path("main.c"))
        assert isinstance(p, CppLanguageParser)

    def test_header_routing(self):
        p = get_parser_for_file(Path("utils.h"))
        assert isinstance(p, CppLanguageParser)

    def test_unknown_returns_none(self):
        p = get_parser_for_file(Path("data.csv"))
        assert p is None

    def test_case_insensitive(self):
        # Path suffix is already lowered inside get_parser_for_file
        p = get_parser_for_file(Path("Main.PY"))
        assert p is not None


# ── get_all_supported_extensions ────────────────────────────────────────────

class TestGetAllSupportedExtensions:
    def test_returns_set(self):
        exts = get_all_supported_extensions()
        assert isinstance(exts, set)

    def test_includes_all(self):
        exts = get_all_supported_extensions()
        expected = {
            ".py", ".pyw",
            ".ts", ".tsx", ".js", ".jsx",
            ".java",
            ".go",
            ".rs",
            ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx",
        }
        assert expected == exts
