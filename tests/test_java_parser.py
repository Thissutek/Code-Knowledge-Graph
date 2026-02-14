"""
Tests for the Java tree-sitter parser.
"""
from pathlib import Path

from src.parsers.java_parser import JavaLanguageParser
from tests.conftest import SAMPLE_JAVA, SAMPLE_JAVA_INNER_CLASSES


def _parse(code: str, filename: str = "Test.java"):
    parser = JavaLanguageParser()
    return parser.parse_file(Path(filename), code)


# ── Config ──────────────────────────────────────────────────────────────────

class TestJavaConfig:
    def test_extensions(self):
        p = JavaLanguageParser()
        assert ".java" in p.config.extensions

    def test_can_parse(self):
        p = JavaLanguageParser()
        assert p.can_parse(Path("Main.java"))
        assert not p.can_parse(Path("main.py"))


# ── Classes ─────────────────────────────────────────────────────────────────

class TestJavaClasses:
    def test_class_detected(self):
        r = _parse(SAMPLE_JAVA)
        names = [c.name for c in r["classes"]]
        assert "UserService" in names
        assert "User" in names

    def test_class_language_type(self):
        r = _parse(SAMPLE_JAVA)
        us = next(c for c in r["classes"] if c.name == "UserService")
        assert us.language_type == "class"

    def test_class_line_numbers(self):
        r = _parse(SAMPLE_JAVA)
        us = next(c for c in r["classes"] if c.name == "UserService")
        assert us.start_line > 0
        assert us.end_line >= us.start_line


# ── Enums ───────────────────────────────────────────────────────────────────

class TestJavaEnums:
    def test_enum_detected(self):
        r = _parse(SAMPLE_JAVA)
        enums = [c for c in r["classes"] if c.language_type == "enum"]
        names = [e.name for e in enums]
        assert "Role" in names


# ── Interfaces ──────────────────────────────────────────────────────────────

class TestJavaInterfaces:
    def test_interface_detected(self):
        r = _parse(SAMPLE_JAVA)
        ifaces = r.get("interfaces", [])
        names = [i.name for i in ifaces]
        assert "Identifiable" in names

    def test_interface_methods(self):
        r = _parse(SAMPLE_JAVA)
        ifaces = r.get("interfaces", [])
        ident = next(i for i in ifaces if i.name == "Identifiable")
        assert "getId" in ident.methods


# ── Methods ─────────────────────────────────────────────────────────────────

class TestJavaMethods:
    def test_methods_extracted(self):
        r = _parse(SAMPLE_JAVA)
        names = [f.name for f in r["functions"]]
        assert "findById" in names
        assert "addUser" in names

    def test_constructor(self):
        r = _parse(SAMPLE_JAVA)
        names = [f.name for f in r["functions"]]
        assert "UserService" in names

    def test_visibility(self):
        r = _parse(SAMPLE_JAVA)
        find = next(f for f in r["functions"] if f.name == "findById")
        assert find.visibility == "public"
        validate = next(f for f in r["functions"] if f.name == "validate")
        assert validate.visibility == "private"

    def test_static_method(self):
        code = (
            "class Util {\n"
            "    public static int max(int a, int b) { return a > b ? a : b; }\n"
            "}\n"
        )
        r = _parse(code)
        mx = next(f for f in r["functions"] if f.name == "max")
        assert mx.is_static is True

    def test_return_type(self):
        r = _parse(SAMPLE_JAVA)
        find = next(f for f in r["functions"] if f.name == "findById")
        # Java return type comes from tree-sitter; may be 'Optional' or full generic
        assert find.return_type is not None

    def test_parameters(self):
        r = _parse(SAMPLE_JAVA)
        find = next(f for f in r["functions"] if f.name == "findById")
        assert len(find.parameters) >= 1
        assert find.parameters[0].name == "id"


# ── Imports ─────────────────────────────────────────────────────────────────

class TestJavaImports:
    def test_imports_extracted(self):
        r = _parse(SAMPLE_JAVA)
        sources = [i.source for i in r["imports"]]
        assert any("java.util.List" in s for s in sources)
        assert any("java.util.Map" in s for s in sources)


# ── Relationships ───────────────────────────────────────────────────────────

class TestJavaRelationships:
    def test_has_method(self):
        r = _parse(SAMPLE_JAVA)
        hm = [rel for rel in r["relationships"] if rel.rel_type == "HAS_METHOD"]
        assert len(hm) > 0

    def test_implements(self):
        r = _parse(SAMPLE_JAVA)
        impl = [rel for rel in r["relationships"] if rel.rel_type == "IMPLEMENTS"]
        # User implements Identifiable
        assert any("Identifiable" in rel.target_id for rel in impl)


# ── Function calls ─────────────────────────────────────────────────────────

class TestJavaFunctionCalls:
    def test_method_calls_extracted(self):
        r = _parse(SAMPLE_JAVA)
        fc = r.get("function_calls", {})
        # findById calls Optional.ofNullable and users.get
        find_calls = {k: v for k, v in fc.items() if ":findById" in k}
        assert len(find_calls) > 0
        all_names = [name for calls in find_calls.values() for name, _ in calls]
        assert "ofNullable" in all_names
        assert "get" in all_names

    def test_constructor_calls_extracted(self):
        r = _parse(SAMPLE_JAVA)
        fc = r.get("function_calls", {})
        # UserService constructor creates new HashMap
        ctor_calls = {k: v for k, v in fc.items() if ":UserService:UserService" in k}
        assert len(ctor_calls) > 0
        all_names = [name for calls in ctor_calls.values() for name, _ in calls]
        assert "HashMap" in all_names


# ── Inner classes ──────────────────────────────────────────────────────────

class TestJavaInnerClasses:
    """Tests for Java inner class ID collision fix."""

    def setup_method(self):
        self.result = _parse(SAMPLE_JAVA_INNER_CLASSES, "Container.java")
        self.classes = self.result["classes"]
        self.functions = self.result["functions"]
        self.variables = self.result["variables"]
        self.relationships = self.result["relationships"]

    def test_inner_class_ids_are_unique(self):
        inners = [c for c in self.classes if c.name == "Inner"]
        assert len(inners) == 2
        assert inners[0].id != inners[1].id

    def test_inner_class_ids_include_parent_name(self):
        inners = [c for c in self.classes if c.name == "Inner"]
        ids = {c.id for c in inners}
        assert "Container.java:Outer1:Inner" in ids
        assert "Container.java:Outer2:Inner" in ids

    def test_inner_method_ids_are_unique(self):
        do_works = [f for f in self.functions if f.name == "doWork"]
        assert len(do_works) == 2
        assert do_works[0].id != do_works[1].id

    def test_inner_method_ids_include_full_hierarchy(self):
        do_works = [f for f in self.functions if f.name == "doWork"]
        ids = {f.id for f in do_works}
        assert "Container.java:Outer1:Inner:doWork" in ids
        assert "Container.java:Outer2:Inner:doWork" in ids

    def test_inner_variable_ids_are_unique(self):
        inner_ids = {c.id for c in self.classes if c.name == "Inner"}
        inner_vars = [
            v for v in self.variables
            if any(
                r.source_id in inner_ids and r.target_id == v.id
                for r in self.relationships if r.rel_type == "HAS_VARIABLE"
            )
        ]
        assert len(inner_vars) == 2
        assert inner_vars[0].id != inner_vars[1].id

    def test_inner_class_relationships_point_to_correct_parents(self):
        inner_rels = [
            r for r in self.relationships
            if r.rel_type == "HAS_VARIABLE"
            and r.properties
            and r.properties.get("kind") == "inner_class"
        ]
        source_target = {(r.source_id, r.target_id) for r in inner_rels}
        assert ("Container.java:Outer1", "Container.java:Outer1:Inner") in source_target
        assert ("Container.java:Outer2", "Container.java:Outer2:Inner") in source_target

    def test_top_level_class_ids_unchanged(self):
        outers = [c for c in self.classes if c.name in ("Outer1", "Outer2")]
        ids = {c.id for c in outers}
        assert "Container.java:Outer1" in ids
        assert "Container.java:Outer2" in ids
