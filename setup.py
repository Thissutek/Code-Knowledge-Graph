#!/usr/bin/env python3
from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="code-kag",
    version="0.1.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="Code Knowledge Graph - KAG-based code search and context retrieval",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/code-kag",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.10",
    install_requires=[
        "neo4j>=5.0.0",
        "mcp>=0.1.0",
        "tree-sitter>=0.23.0",
        "tree-sitter-typescript>=0.23.0",
        "tree-sitter-java>=0.23.0",
        "tree-sitter-go>=0.23.0",
        "tree-sitter-rust>=0.23.0",
        "tree-sitter-c>=0.23.0",
        "tree-sitter-cpp>=0.23.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "black>=23.0.0",
            "mypy>=1.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "code-kag=cli:main",
            "code-kag-server=src.mcp_server:main",
        ],
    },
)
