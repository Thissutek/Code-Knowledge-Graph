#!/usr/bin/env python3
"""Docker health check script for Code-KAG."""
import os
import sys

from neo4j import GraphDatabase


def main():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    username = os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        driver.verify_connectivity()
    finally:
        driver.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
