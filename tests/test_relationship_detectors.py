"""Tests for language-specific relationship detectors."""
import pytest
from src.relationships.base import DetectedRelationship
from src.relationships.factory import RelationshipDetectorFactory
from src.relationships.python_detector import PythonRelationshipDetector


# ── Factory ────────────────────────────────────────────────────────────────

class TestRelationshipDetectorFactory:
    def setup_method(self):
        RelationshipDetectorFactory.clear_cache()

    def test_returns_python_detector_for_py(self):
        d = RelationshipDetectorFactory.get_detector('src/foo.py')
        assert d is not None
        assert '.py' in d.supported_extensions()

    def test_returns_none_for_unsupported_extension(self):
        d = RelationshipDetectorFactory.get_detector('file.unknown')
        assert d is None

    def test_caches_detector_instance(self):
        d1 = RelationshipDetectorFactory.get_detector('a.py')
        d2 = RelationshipDetectorFactory.get_detector('b.py')
        assert d1 is d2  # same cached instance

    def test_clear_cache(self):
        RelationshipDetectorFactory.get_detector('a.py')
        RelationshipDetectorFactory.clear_cache()
        # After clear, a new instance is created
        d = RelationshipDetectorFactory.get_detector('a.py')
        assert d is not None


# ── Python Detector ────────────────────────────────────────────────────────

class TestPythonDetector:
    def setup_method(self):
        self.detector = PythonRelationshipDetector()

    def test_supported_extensions(self):
        assert '.py' in self.detector.supported_extensions()

    def test_detects_function_call(self):
        code = "def foo():\n    bar()\n"
        rels = self.detector.detect(code, 'test.py')
        calls = [r for r in rels if r.relationship_type == 'CALLS']
        assert any(r.target_name == 'bar' for r in calls)

    def test_detects_extends(self):
        code = "class Child(Parent):\n    pass\n"
        rels = self.detector.detect(code, 'test.py')
        extends = [r for r in rels if r.relationship_type == 'EXTENDS']
        assert len(extends) == 1
        assert extends[0].source_name == 'Child'
        assert extends[0].target_name == 'Parent'

    def test_detects_instantiation(self):
        code = "def create():\n    obj = MyClass()\n"
        rels = self.detector.detect(code, 'test.py')
        insts = [r for r in rels if r.relationship_type == 'INSTANTIATES']
        assert any(r.target_name == 'MyClass' for r in insts)

    def test_confidence_range(self):
        code = "class A(B):\n    def m(self):\n        foo()\n"
        rels = self.detector.detect(code, 'test.py')
        for r in rels:
            assert 0.0 <= r.confidence <= 1.0

    def test_line_numbers_set(self):
        code = "def f():\n    g()\n"
        rels = self.detector.detect(code, 'test.py')
        for r in rels:
            assert r.line_number > 0

    def test_syntax_error_returns_empty(self):
        rels = self.detector.detect("def (broken:", 'test.py')
        assert rels == []

    def test_empty_file_returns_empty(self):
        rels = self.detector.detect("", 'test.py')
        assert rels == []

    def test_context_string_set(self):
        code = "class Child(Parent):\n    pass\n"
        rels = self.detector.detect(code, 'test.py')
        extends = [r for r in rels if r.relationship_type == 'EXTENDS']
        assert extends[0].context != ''

    def test_detection_method_set(self):
        code = "class Child(Parent):\n    pass\n"
        rels = self.detector.detect(code, 'test.py')
        extends = [r for r in rels if r.relationship_type == 'EXTENDS']
        assert extends[0].detection_method.startswith('AST_')

    def test_method_call_includes_class_context(self):
        code = "class Foo:\n    def bar(self):\n        baz()\n"
        rels = self.detector.detect(code, 'test.py')
        calls = [r for r in rels if r.relationship_type == 'CALLS' and r.target_name == 'baz']
        assert any('Foo' in r.source_name for r in calls)

    def test_multiple_extends(self):
        code = "class C(A, B):\n    pass\n"
        rels = self.detector.detect(code, 'test.py')
        extends = [r for r in rels if r.relationship_type == 'EXTENDS']
        targets = {r.target_name for r in extends}
        assert 'A' in targets and 'B' in targets

    def test_detected_relationship_dataclass_fields(self):
        r = DetectedRelationship(
            source_name='A', target_name='B',
            relationship_type='CALLS', confidence=0.9,
            detection_method='AST_call', line_number=5, file_path='f.py',
        )
        assert r.context == ''
        assert r.metadata == {}


# ── Parser integration ─────────────────────────────────────────────────────

class TestParserDetectorIntegration:
    """Integration: parser stores source and detectors enrich relationships."""

    def test_pending_source_code_cleared_after_parse(self, tmp_path):
        from src.parser import CodebaseParser
        (tmp_path / 'a.py').write_text('def foo():\n    bar()\n')
        parser = CodebaseParser(str(tmp_path), 'test')
        parser.parse()
        assert parser._pending_source_code == {}

    def test_detector_results_added_to_codebase(self, tmp_path):
        from src.parser import CodebaseParser
        code = "class Child(Parent):\n    pass\nclass Parent:\n    pass\n"
        (tmp_path / 'a.py').write_text(code)
        parser = CodebaseParser(str(tmp_path), 'test')
        codebase = parser.parse()
        rel_types = {r.rel_type for r in codebase.relationships}
        assert 'EXTENDS' in rel_types
