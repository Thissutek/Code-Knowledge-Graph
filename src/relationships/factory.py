"""Factory that returns the right relationship detector for a given file."""
from pathlib import Path
from typing import Dict, Optional

from .base import BaseRelationshipDetector

# Extension → language key
_EXTENSION_MAP: Dict[str, str] = {
    '.py': 'python',
    '.ts': 'typescript',
    '.tsx': 'typescript',
    '.js': 'typescript',   # reuse TS detector (tree-sitter-typescript handles JS too)
    '.jsx': 'typescript',
    '.go': 'go',
    '.java': 'java',
    '.rs': 'rust',
}

# Lazily populated cache
_cache: Dict[str, BaseRelationshipDetector] = {}


def _create_detector(language: str) -> BaseRelationshipDetector:
    if language == 'python':
        from .python_detector import PythonRelationshipDetector
        return PythonRelationshipDetector()
    if language == 'typescript':
        from .typescript_detector import TypeScriptRelationshipDetector
        return TypeScriptRelationshipDetector()
    if language == 'go':
        from .go_detector import GoRelationshipDetector
        return GoRelationshipDetector()
    if language == 'java':
        from .java_detector import JavaRelationshipDetector
        return JavaRelationshipDetector()
    if language == 'rust':
        from .rust_detector import RustRelationshipDetector
        return RustRelationshipDetector()
    raise ValueError(f'Unknown language: {language}')


class RelationshipDetectorFactory:
    """Returns a cached detector instance for a given file path."""

    @staticmethod
    def get_detector(file_path: str) -> Optional[BaseRelationshipDetector]:
        """Return the detector for *file_path*, or None if unsupported."""
        ext = Path(file_path).suffix.lower()
        language = _EXTENSION_MAP.get(ext)
        if language is None:
            return None
        if language not in _cache:
            try:
                _cache[language] = _create_detector(language)
            except Exception:
                return None
        return _cache[language]

    @staticmethod
    def clear_cache() -> None:
        """Clear the detector cache (useful in tests)."""
        _cache.clear()
