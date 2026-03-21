"""Language-specific relationship detectors for Code-KAG."""
from .base import BaseRelationshipDetector, DetectedRelationship
from .factory import RelationshipDetectorFactory

__all__ = [
    'BaseRelationshipDetector',
    'DetectedRelationship',
    'RelationshipDetectorFactory',
]
