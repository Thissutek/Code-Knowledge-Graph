"""
Shared fixtures for the Code-KAG test suite.
"""
import os
import sys
import shutil
import tempfile
import subprocess
from pathlib import Path

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Sample source snippets used across multiple test modules
# ---------------------------------------------------------------------------

SAMPLE_PYTHON = '''\
"""Sample Python module"""
import os
from typing import List, Optional

MAX_RETRIES = 3

class Config:
    """Application configuration"""
    host: str = "localhost"
    port: int = 8080

    def to_dict(self) -> dict:
        """Convert config to dictionary"""
        return {"host": self.host, "port": self.port}

class Service(Config):
    """Base service extending Config"""
    def __init__(self, name: str):
        self.name = name

    async def start(self) -> bool:
        """Start the service"""
        return True

    def _internal(self):
        pass

    def __private(self):
        pass

def create_service(name: str) -> Service:
    """Factory function"""
    svc = Service(name)
    svc.start()
    return svc

def main():
    svc = create_service("web")
    print(svc.to_dict())
'''

SAMPLE_TYPESCRIPT = '''\
import { EventEmitter } from "events";
import axios from "axios";

interface Fetchable {
  fetch(url: string): Promise<any>;
}

class HttpClient extends EventEmitter implements Fetchable {
  private baseUrl: string;
  timeout: number;

  constructor(baseUrl: string, timeout: number = 5000) {
    super();
    this.baseUrl = baseUrl;
    this.timeout = timeout;
  }

  async fetch(url: string): Promise<any> {
    return axios.get(`${this.baseUrl}/${url}`, { timeout: this.timeout });
  }

  static create(baseUrl: string): HttpClient {
    return new HttpClient(baseUrl);
  }
}

enum LogLevel {
  DEBUG,
  INFO,
  WARN,
  ERROR
}

const greet = (name: string): string => `Hello, ${name}`;

function add(a: number, b: number): number {
  return a + b;
}

export { HttpClient, LogLevel, greet, add };
'''

SAMPLE_JAVA = '''\
package com.example.app;

import java.util.List;
import java.util.Map;
import java.util.Optional;

public class UserService {
    private final Map<String, User> users;

    public UserService() {
        this.users = new java.util.HashMap<>();
    }

    public Optional<User> findById(String id) {
        return Optional.ofNullable(users.get(id));
    }

    public void addUser(User user) {
        users.put(user.getId(), user);
    }

    private void validate(User user) {
        if (user == null) throw new IllegalArgumentException("null user");
    }
}

interface Identifiable {
    String getId();
}

enum Role {
    ADMIN,
    USER,
    GUEST
}

class User implements Identifiable {
    private String id;
    private String name;
    private Role role;

    public User(String id, String name) {
        this.id = id;
        this.name = name;
        this.role = Role.USER;
    }

    @Override
    public String getId() {
        return id;
    }
}
'''

SAMPLE_GO = '''\
package main

import (
    "fmt"
    "os"
    "sync"
)

type Config struct {
    Host string
    Port int
}

type Server struct {
    Config
    mu      sync.Mutex
    running bool
}

type Handler interface {
    Handle(req string) string
}

func NewServer(host string, port int) *Server {
    return &Server{
        Config: Config{Host: host, Port: port},
    }
}

func (s *Server) Start() error {
    s.mu.Lock()
    defer s.mu.Unlock()
    s.running = true
    fmt.Printf("Server started on %s:%d\\n", s.Host, s.Port)
    return nil
}

func (s *Server) Stop() {
    s.mu.Lock()
    defer s.mu.Unlock()
    s.running = false
}

func main() {
    srv := NewServer("localhost", 8080)
    if err := srv.Start(); err != nil {
        fmt.Fprintln(os.Stderr, err)
        os.Exit(1)
    }
}

const MaxConnections = 100
var DefaultTimeout int = 30
'''

SAMPLE_RUST = '''\
use std::collections::HashMap;
use std::fmt;

pub struct Cache {
    data: HashMap<String, String>,
    capacity: usize,
}

pub enum CacheError {
    Full,
    NotFound,
    InvalidKey(String),
}

pub trait Storage {
    fn get(&self, key: &str) -> Option<&String>;
    fn set(&mut self, key: String, value: String) -> Result<(), CacheError>;
}

impl Cache {
    pub fn new(capacity: usize) -> Self {
        Cache {
            data: HashMap::new(),
            capacity,
        }
    }

    pub fn len(&self) -> usize {
        self.data.len()
    }
}

impl Storage for Cache {
    fn get(&self, key: &str) -> Option<&String> {
        self.data.get(key)
    }

    fn set(&mut self, key: String, value: String) -> Result<(), CacheError> {
        if self.data.len() >= self.capacity {
            return Err(CacheError::Full);
        }
        self.data.insert(key, value);
        Ok(())
    }
}

impl fmt::Display for CacheError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            CacheError::Full => write!(f, "cache is full"),
            CacheError::NotFound => write!(f, "not found"),
            CacheError::InvalidKey(k) => write!(f, "invalid key: {}", k),
        }
    }
}

const MAX_CACHE_SIZE: usize = 10_000;
'''

SAMPLE_CPP = '''\
#include <iostream>
#include <string>
#include <vector>
#include "config.h"

namespace app {

class Animal {
public:
    Animal(const std::string& name, int age) : name_(name), age_(age) {}
    virtual ~Animal() = default;
    virtual std::string speak() const = 0;
    std::string getName() const { return name_; }
    int getAge() const { return age_; }

protected:
    std::string name_;
    int age_;
};

class Dog : public Animal {
public:
    Dog(const std::string& name, int age) : Animal(name, age) {}
    std::string speak() const override { return "Woof!"; }
};

struct Point {
    double x;
    double y;
};

enum class Color { Red, Green, Blue };

}  // namespace app

int main(int argc, char* argv[]) {
    app::Dog d("Rex", 3);
    std::cout << d.speak() << std::endl;
    return 0;
}
'''

SAMPLE_C = '''\
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct Node {
    int value;
    struct Node* next;
};

void push(struct Node** head, int value) {
    struct Node* node = malloc(sizeof(struct Node));
    node->value = value;
    node->next = *head;
    *head = node;
}

int pop(struct Node** head) {
    if (*head == NULL) return -1;
    struct Node* top = *head;
    int val = top->value;
    *head = top->next;
    free(top);
    return val;
}

int main() {
    struct Node* stack = NULL;
    push(&stack, 10);
    push(&stack, 20);
    printf("%d\\n", pop(&stack));
    return 0;
}
'''


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    """Provide a temporary directory that is cleaned up after the test."""
    d = tempfile.mkdtemp(prefix="code-kag-test-")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sample_repo(tmp_dir):
    """Create a multi-language sample repository."""
    files = {
        "src/main.py": SAMPLE_PYTHON,
        "src/__init__.py": "",
        "src/client.ts": SAMPLE_TYPESCRIPT,
        "src/UserService.java": SAMPLE_JAVA,
        "cmd/server.go": SAMPLE_GO,
        "src/cache.rs": SAMPLE_RUST,
        "src/main.cpp": SAMPLE_CPP,
        "lib/stack.c": SAMPLE_C,
    }
    for rel_path, content in files.items():
        fp = tmp_dir / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
    return tmp_dir


@pytest.fixture
def python_only_repo(tmp_dir):
    """Create a Python-only sample repository (for regression testing)."""
    files = {
        "src/__init__.py": "",
        "src/main.py": SAMPLE_PYTHON,
        "src/services/__init__.py": "",
        "src/services/cache.py": (
            '"""Cache module"""\n'
            'from ..main import Config\n\n'
            'class CacheService:\n'
            '    def __init__(self, config: Config):\n'
            '        self._cache = {}\n'
            '    def get(self, key: str):\n'
            '        return self._cache.get(key)\n'
            '    def set(self, key: str, value):\n'
            '        self._cache[key] = value\n'
        ),
    }
    for rel_path, content in files.items():
        fp = tmp_dir / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
    return tmp_dir


@pytest.fixture
def git_repo(tmp_dir):
    """Create a temporary git repository."""
    subprocess.run(
        ["git", "init", str(tmp_dir)],
        capture_output=True, check=True,
    )
    # Write a sample file and make an initial commit
    (tmp_dir / "README.md").write_text("# Test repo\n")
    subprocess.run(
        ["git", "-C", str(tmp_dir), "add", "."],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_dir), "commit", "-m", "initial"],
        capture_output=True, check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@t"},
    )
    return tmp_dir
