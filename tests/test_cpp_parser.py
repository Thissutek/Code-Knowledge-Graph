"""
Tests for the C/C++ tree-sitter parser.
"""
from pathlib import Path

from src.parsers.cpp_parser import CppLanguageParser
from tests.conftest import SAMPLE_CPP, SAMPLE_C


def _parse(code: str, filename: str = "main.cpp"):
    parser = CppLanguageParser()
    return parser.parse_file(Path(filename), code)


# ── Config ──────────────────────────────────────────────────────────────────

class TestCppConfig:
    def test_extensions(self):
        p = CppLanguageParser()
        exts = p.config.extensions
        for e in (".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx"):
            assert e in exts

    def test_can_parse(self):
        p = CppLanguageParser()
        assert p.can_parse(Path("main.cpp"))
        assert p.can_parse(Path("header.h"))
        assert p.can_parse(Path("lib.c"))
        assert not p.can_parse(Path("main.rs"))


# ── C++ Classes ─────────────────────────────────────────────────────────────

class TestCppClasses:
    def test_class_detected(self):
        r = _parse(SAMPLE_CPP)
        names = [c.name for c in r["classes"]]
        assert "app::Animal" in names
        assert "app::Dog" in names

    def test_class_language_type(self):
        r = _parse(SAMPLE_CPP)
        animal = next(c for c in r["classes"] if c.name == "app::Animal")
        assert animal.language_type == "class"

    def test_class_inheritance(self):
        r = _parse(SAMPLE_CPP)
        dog = next(c for c in r["classes"] if c.name == "app::Dog")
        assert "Animal" in dog.base_classes

    def test_struct_detected(self):
        r = _parse(SAMPLE_CPP)
        point = next(c for c in r["classes"] if "Point" in c.name)
        assert point.language_type == "struct"


# ── C++ Enums ───────────────────────────────────────────────────────────────

class TestCppEnums:
    def test_enum_detected(self):
        r = _parse(SAMPLE_CPP)
        enums = [c for c in r["classes"] if c.language_type == "enum"]
        names = [e.name for e in enums]
        assert any("Color" in n for n in names)


# ── C++ Functions ───────────────────────────────────────────────────────────

class TestCppFunctions:
    def test_methods_extracted(self):
        r = _parse(SAMPLE_CPP)
        names = [f.name for f in r["functions"]]
        assert "getName" in names
        assert "speak" in names

    def test_free_function(self):
        r = _parse(SAMPLE_CPP)
        main_fn = next(f for f in r["functions"] if f.name == "main")
        assert main_fn.is_method is False

    def test_method_is_method(self):
        r = _parse(SAMPLE_CPP)
        get_name = next(f for f in r["functions"] if f.name == "getName")
        assert get_name.is_method is True

    def test_constructor(self):
        r = _parse(SAMPLE_CPP)
        names = [f.name for f in r["functions"]]
        assert "Animal" in names  # constructor
        assert "Dog" in names

    def test_destructor(self):
        r = _parse(SAMPLE_CPP)
        names = [f.name for f in r["functions"]]
        assert "~Animal" in names


# ── C++ Includes ────────────────────────────────────────────────────────────

class TestCppIncludes:
    def test_system_includes(self):
        r = _parse(SAMPLE_CPP)
        sources = [i.source for i in r["imports"]]
        assert "iostream" in sources
        assert "string" in sources
        assert "vector" in sources

    def test_local_include(self):
        r = _parse(SAMPLE_CPP)
        sources = [i.source for i in r["imports"]]
        assert "config.h" in sources

    def test_system_vs_local_flag(self):
        r = _parse(SAMPLE_CPP)
        iostream = next(i for i in r["imports"] if i.source == "iostream")
        config_h = next(i for i in r["imports"] if i.source == "config.h")
        assert iostream.is_external is True
        assert config_h.is_external is False


# ── C++ Namespace ───────────────────────────────────────────────────────────

class TestCppNamespace:
    def test_classes_namespaced(self):
        r = _parse(SAMPLE_CPP)
        names = [c.name for c in r["classes"]]
        assert any(n.startswith("app::") for n in names)


# ── Pure C ──────────────────────────────────────────────────────────────────

class TestCParsing:
    def test_c_structs(self):
        r = _parse(SAMPLE_C, "stack.c")
        names = [c.name for c in r["classes"]]
        assert "Node" in names

    def test_c_struct_language_type(self):
        r = _parse(SAMPLE_C, "stack.c")
        node = next(c for c in r["classes"] if c.name == "Node")
        assert node.language_type == "struct"

    def test_c_functions(self):
        r = _parse(SAMPLE_C, "stack.c")
        names = [f.name for f in r["functions"]]
        assert "push" in names
        assert "pop" in names
        assert "main" in names

    def test_c_includes(self):
        r = _parse(SAMPLE_C, "stack.c")
        sources = [i.source for i in r["imports"]]
        assert "stdio.h" in sources
        assert "stdlib.h" in sources
        assert "string.h" in sources

    def test_c_function_parameters(self):
        r = _parse(SAMPLE_C, "stack.c")
        push = next(f for f in r["functions"] if f.name == "push")
        assert len(push.parameters) >= 2
