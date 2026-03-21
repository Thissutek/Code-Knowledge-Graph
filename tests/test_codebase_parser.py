"""
Tests for CodebaseParser — full and incremental multi-language parsing.
"""
from pathlib import Path

from src.parser import CodebaseParser


# ── Multi-language full parse ───────────────────────────────────────────────

class TestCodebaseParserMultiLanguage:
    """Parse a mixed-language repo and verify all entity types extracted."""

    def test_parses_all_files(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "multi")
        codebase = parser.parse()
        # Should find: main.py, __init__.py, client.ts, UserService.java,
        #              server.go, cache.rs, main.cpp, stack.c
        assert len(codebase.files) >= 8

    def test_multi_language_label(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "multi")
        codebase = parser.parse()
        assert codebase.repository.language == "multi"

    def test_languages_detected(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "multi")
        codebase = parser.parse()
        languages = {f.language for f in codebase.files}
        assert "Python" in languages
        assert "TypeScript" in languages
        assert "Java" in languages
        assert "Go" in languages
        assert "Rust" in languages
        assert "C/C++" in languages

    def test_classes_from_multiple_languages(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "multi")
        codebase = parser.parse()
        names = [c.name for c in codebase.classes]
        # Python
        assert "Config" in names
        assert "Service" in names
        # TypeScript
        assert "HttpClient" in names
        # Java
        assert "UserService" in names
        # Go struct
        assert any("Server" in n for n in names)
        # Rust struct
        assert "Cache" in names
        # C++ class (namespaced)
        assert any("Animal" in n for n in names)

    def test_functions_from_multiple_languages(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "multi")
        codebase = parser.parse()
        names = [f.name for f in codebase.functions]
        # Python
        assert "create_service" in names
        # TypeScript
        assert "add" in names
        # Java
        assert "findById" in names
        # Go
        assert "NewServer" in names
        # Rust
        assert "new" in names
        # C/C++
        assert "push" in names

    def test_imports_from_multiple_languages(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "multi")
        codebase = parser.parse()
        sources = [i.source for i in codebase.imports]
        # Python
        assert "os" in sources
        # TypeScript
        assert "axios" in sources
        # Go
        assert "fmt" in sources

    def test_relationships_generated(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "multi")
        codebase = parser.parse()
        rel_types = {r.rel_type for r in codebase.relationships}
        assert "CONTAINS_FILE" in rel_types
        assert "DEFINES_CLASS" in rel_types
        assert "DEFINES_FUNCTION" in rel_types
        assert "HAS_METHOD" in rel_types
        assert "IMPORTS" in rel_types

    def test_modules_created(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "multi")
        codebase = parser.parse()
        mod_names = [m.name for m in codebase.modules]
        assert "src" in mod_names

    def test_get_stats(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "multi")
        codebase = parser.parse()
        stats = codebase.get_stats()
        assert stats["files"] >= 8
        assert stats["classes"] >= 5
        assert stats["functions"] >= 10
        assert stats["imports"] >= 5
        assert stats["relationships"] >= 10


# ── Incremental parsing ────────────────────────────────────────────────────

class TestCodebaseParserIncremental:
    def test_incremental_parses_only_specified_files(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "inc-test")
        codebase = parser.parse_incremental(["src/main.py"])

        assert len(codebase.files) == 1
        assert codebase.files[0].name == "main.py"

    def test_incremental_skips_nonexistent(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "inc-test")
        codebase = parser.parse_incremental(["does_not_exist.py"])

        assert len(codebase.files) == 0

    def test_incremental_skips_unsupported_extensions(self, sample_repo):
        # Create a .txt file
        (sample_repo / "notes.txt").write_text("hello")
        parser = CodebaseParser(str(sample_repo), "inc-test")
        codebase = parser.parse_incremental(["notes.txt"])

        assert len(codebase.files) == 0

    def test_incremental_multiple_files(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "inc-test")
        codebase = parser.parse_incremental([
            "src/main.py",
            "src/client.ts",
        ])

        assert len(codebase.files) == 2
        names = {f.name for f in codebase.files}
        assert "main.py" in names
        assert "client.ts" in names

    def test_incremental_entities_extracted(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "inc-test")
        codebase = parser.parse_incremental(["src/main.py"])

        assert len(codebase.classes) >= 2  # Config, Service
        assert len(codebase.functions) >= 4


# ── Call graph resolution ──────────────────────────────────────────────────

class TestCallGraphResolution:
    """Verify CALLS relationships are resolved from all languages."""

    def test_python_calls_resolved(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "call-test")
        codebase = parser.parse()
        calls = [r for r in codebase.relationships if r.rel_type == "CALLS"]
        # main() calls create_service()
        assert any("main" in r.source_id and "create_service" in r.target_id
                    for r in calls)

    def test_non_python_calls_present(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "call-test")
        codebase = parser.parse()
        calls = [r for r in codebase.relationships if r.rel_type == "CALLS"]
        # Should have calls from non-Python languages too
        # Go main calls NewServer, C main calls push, etc.
        call_names = [(r.source_id, r.target_id) for r in calls]
        non_python_calls = [
            (s, t) for s, t in call_names if not s.endswith('.py')
        ]
        # At minimum we should have some non-Python CALLS
        # (Go main->NewServer, C main->push, etc.)
        assert len(non_python_calls) > 0


# ── EXTENDS relationships ───────────────────────────────────────────────────

class TestExtendsRelationships:
    """Verify EXTENDS relationships are resolved across languages."""

    def test_python_extends(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "ext-test")
        codebase = parser.parse()
        extends = [r for r in codebase.relationships if r.rel_type == "EXTENDS"]
        # Service extends Config
        assert any("Service" in r.source_id and "Config" in r.target_id
                    for r in extends)

    def test_cpp_extends(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "ext-test")
        codebase = parser.parse()
        extends = [r for r in codebase.relationships if r.rel_type == "EXTENDS"]
        # Dog extends Animal
        assert any("Dog" in r.source_id and "Animal" in r.target_id
                    for r in extends)


# ── IMPLEMENTS resolution ──────────────────────────────────────────────────

class TestImplementsResolution:
    """Verify IMPLEMENTS target IDs are resolved to full interface IDs."""

    def test_typescript_implements_resolved(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "impl-test")
        codebase = parser.parse()
        impl_rels = [r for r in codebase.relationships
                     if r.rel_type == "IMPLEMENTS"]
        # HttpClient implements Fetchable — target should be fully qualified
        fetchable_rels = [r for r in impl_rels if "HttpClient" in r.source_id]
        assert len(fetchable_rels) > 0
        for r in fetchable_rels:
            assert ':' in r.target_id, (
                f"IMPLEMENTS target should be resolved: {r.target_id}")

    def test_java_implements_resolved(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "impl-test")
        codebase = parser.parse()
        impl_rels = [r for r in codebase.relationships
                     if r.rel_type == "IMPLEMENTS"]
        # User implements Identifiable — target should be fully qualified
        user_rels = [r for r in impl_rels if "User" in r.source_id]
        assert len(user_rels) > 0
        for r in user_rels:
            assert ':' in r.target_id, (
                f"IMPLEMENTS target should be resolved: {r.target_id}")


# ── Ignore directories ──────────────────────────────────────────────────────

class TestIgnoreDirs:
    def test_node_modules_ignored(self, tmp_dir):
        (tmp_dir / "src" / "main.py").parent.mkdir(parents=True)
        (tmp_dir / "src" / "main.py").write_text("x = 1\n")
        (tmp_dir / "node_modules" / "pkg" / "index.js").parent.mkdir(
            parents=True)
        (tmp_dir / "node_modules" / "pkg" / "index.js").write_text(
            "function f() {}\n")

        parser = CodebaseParser(str(tmp_dir), "test")
        codebase = parser.parse()
        paths = [f.path for f in codebase.files]
        assert not any("node_modules" in p for p in paths)

    def test_git_dir_ignored(self, tmp_dir):
        (tmp_dir / "main.py").write_text("x = 1\n")
        (tmp_dir / ".git" / "hooks" / "pre-commit").parent.mkdir(
            parents=True)
        (tmp_dir / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\n")

        parser = CodebaseParser(str(tmp_dir), "test")
        codebase = parser.parse()
        paths = [f.path for f in codebase.files]
        assert not any(".git" in p for p in paths)


# ── Function ID format ─────────────────────────────────────────────────────

class TestFunctionIdFormat:
    """Function and class IDs must use relative paths so MCP queries work."""

    def test_function_ids_are_relative(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "id-test")
        codebase = parser.parse()
        for func in codebase.functions:
            assert not func.id.startswith('/'), (
                f"Function ID should be relative, got: {func.id}")

    def test_class_ids_are_relative(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "id-test")
        codebase = parser.parse()
        for cls in codebase.classes:
            assert not cls.id.startswith('/'), (
                f"Class ID should be relative, got: {cls.id}")

    def test_calls_relationship_ids_are_relative(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "id-test")
        codebase = parser.parse()
        calls = [r for r in codebase.relationships if r.rel_type == "CALLS"]
        for rel in calls:
            assert not rel.source_id.startswith('/'), (
                f"CALLS source should be relative, got: {rel.source_id}")
            assert not rel.target_id.startswith('/'), (
                f"CALLS target should be relative, got: {rel.target_id}")


# ── Pending dict cleanup ────────────────────────────────────────────────────

class TestPendingDictCleanup:
    """Verify pending call dicts are cleared after _resolve_relationships()."""

    def test_pending_dicts_empty_after_parse(self, sample_repo):
        parser = CodebaseParser(str(sample_repo), "cleanup-test")
        parser.parse()
        assert parser._pending_function_calls == {}
        assert parser._pending_class_usages == {}
