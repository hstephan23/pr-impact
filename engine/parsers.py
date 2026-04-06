"""Language-specific import/include regex patterns and resolution functions.

Each ``_resolve_*`` function takes an import path (and context like the source
file, project directory, and set of known files) and returns a tuple of
``(resolved_path, is_external)``.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Match

# =========================================================================
# Regex patterns
# =========================================================================

# C/C++: #include <header> or #include "header"
INCLUDE_RE = re.compile(r'#include\s*(<|")([^>"]+)(>|")')

# JS/TS: import ... from 'path', import 'path', require('path')
JS_IMPORT_RE = re.compile(
    r'''(?:import\s+(?:[\s\S]*?\s+from\s+)?['"]([^'"]+)['"]'''
    r'''|require\s*\(\s*['"]([^'"]+)['"]\s*\))'''
)

# Python: import foo, import foo.bar, from foo import bar, from . import bar
PY_FROM_IMPORT_RE = re.compile(
    r'^from\s+(\.{0,3}[\w.]*)\s+import\s+(.+)$', re.MULTILINE
)
PY_IMPORT_RE = re.compile(
    r'^import\s+([\w.]+(?:\s*,\s*[\w.]+)*)\s*$', re.MULTILINE
)
# Collapse parenthesised Python imports onto a single line so the regex above
# can match them.  e.g.  from foo import (\n  a,\n  b\n) → from foo import a, b
_PY_MULTILINE_IMPORT_RE = re.compile(
    r'^(from\s+\S+\s+import\s*)\(\s*([^)]*)\)', re.MULTILINE | re.DOTALL
)

# Java: import com.example.Foo; or import static com.example.Foo.bar;
JAVA_IMPORT_RE = re.compile(
    r'^import\s+(?:static\s+)?([\w.*]+)\s*;', re.MULTILINE
)

# Go: import "path" or import ( "path" ... )
GO_IMPORT_RE = re.compile(
    r'import\s+(?:\(\s*((?:[^)]*?))\s*\)|"([^"]+)")', re.DOTALL
)
GO_IMPORT_PATH_RE = re.compile(r'"([^"]+)"')

# Rust: use path::to::thing; pub use re_export; mod foo; extern crate bar;
RUST_USE_RE = re.compile(r'^\s*(?:pub\s+)?use\s+([\w:]+)', re.MULTILINE)
RUST_MOD_RE = re.compile(r'^\s*(?:pub(?:\([\w:]+\))?\s+)?mod\s+(\w+)\s*[;{]', re.MULTILINE)
RUST_EXTERN_RE = re.compile(r'^\s*extern\s+crate\s+(\w+)(?:\s+as\s+\w+)?\s*;', re.MULTILINE)

# C#: using System; using System.Collections.Generic; using static Foo.Bar;
CS_USING_RE = re.compile(
    r'^using\s+(?:static\s+)?([\w.]+)\s*;', re.MULTILINE
)

# C# namespace declaration (for building namespace maps)
CS_NAMESPACE_RE = re.compile(
    r'^\s*namespace\s+([\w.]+)', re.MULTILINE
)

# Swift: import ModuleName, import struct ModuleName.Type, @testable import Foo
SWIFT_IMPORT_RE = re.compile(
    r'^\s*(?:@\w+\s+)?import\s+(?:class\s+|struct\s+|enum\s+|protocol\s+|typealias\s+|func\s+|var\s+|let\s+)?([\w.]+)', re.MULTILINE
)

# Ruby: require 'path', require "path", require_relative 'path', load 'path'
RUBY_REQUIRE_RE = re.compile(
    r'''^\s*(?:require_relative|require|load)\s+['"]([\w.\/\-]+)['"]''', re.MULTILINE
)
RUBY_REQUIRE_RELATIVE_RE = re.compile(
    r'''^\s*require_relative\s+['"]([\w.\/\-]+)['"]''', re.MULTILINE
)

# Kotlin: import com.example.Foo or import com.example.Foo as Bar
KOTLIN_IMPORT_RE = re.compile(
    r'^import\s+([\w.*]+)(?:\s+as\s+\w+)?\s*$', re.MULTILINE
)

# Scala: import com.example.Foo, import com.example.{Foo, Bar}, import com.example._
SCALA_IMPORT_RE = re.compile(
    r'^import\s+([\w.*]+(?:\.\{[^}]+\})?)\s*$', re.MULTILINE
)

# PHP: use App\Models\User; require/include 'path'; namespace App\Models;
PHP_USE_RE = re.compile(
    r'^\s*use\s+([\w\\]+)(?:\s+as\s+\w+)?\s*;', re.MULTILINE
)
PHP_REQUIRE_RE = re.compile(
    r'''^\s*(?:require_once|include_once|require|include)\s*[\(]?\s*['"]([\w.\/\-]+)['"]\s*[\)]?\s*;''', re.MULTILINE
)
PHP_NAMESPACE_RE = re.compile(
    r'^\s*namespace\s+([\w\\]+)\s*;', re.MULTILINE
)

# Dart/Flutter: import 'package:foo/bar.dart'; import 'path/to/file.dart';
DART_IMPORT_RE = re.compile(
    r'''^\s*import\s+['"]([\w:\/.\-]+)['"]\s*(?:as\s+\w+\s*)?(?:show\s+[\w,\s]+)?(?:hide\s+[\w,\s]+)?;''', re.MULTILINE
)

# Elixir: alias MyApp.Models.User, import MyApp.Utils, use GenServer, require Logger
ELIXIR_ALIAS_RE = re.compile(
    r'^\s*(?:alias|import|use|require)\s+([\w.]+)', re.MULTILINE
)

# Lua: require("module"), require "module", require 'module'
LUA_REQUIRE_RE = re.compile(
    r'''require\s*[\(]?\s*['"]([^'"]+)['"]\s*[\)]?''', re.MULTILINE
)

# Zig: @import("file.zig"), @import("std")
ZIG_IMPORT_RE = re.compile(
    r'@import\s*\(\s*"([^"]+)"\s*\)', re.MULTILINE
)

# Haskell: import Module.Name, import qualified Module.Name as Alias
HASKELL_IMPORT_RE = re.compile(
    r'^\s*import\s+(?:qualified\s+)?([\w.]+)', re.MULTILINE
)

# R: library(pkg), require(pkg), source("file.R")
R_LIBRARY_RE = re.compile(
    r'''^\s*(?:library|require)\s*\(\s*(?:['"]?([\w.]+)['"]?)\s*\)''', re.MULTILINE
)
R_SOURCE_RE = re.compile(
    r'''^\s*source\s*\(\s*['"]([^'"]+)['"]\s*\)''', re.MULTILINE
)


# =========================================================================
# File extension groups
# =========================================================================

C_EXTENSIONS = ('.c',)
H_EXTENSIONS = ('.h',)
CPP_EXTENSIONS = ('.cpp', '.cc', '.cxx', '.hpp', '.hxx')
JS_EXTENSIONS = ('.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx')
PY_EXTENSIONS = ('.py',)
JAVA_EXTENSIONS = ('.java',)
GO_EXTENSIONS = ('.go',)
RUST_EXTENSIONS = ('.rs',)
CS_EXTENSIONS = ('.cs',)
SWIFT_EXTENSIONS = ('.swift',)
RUBY_EXTENSIONS = ('.rb',)
KOTLIN_EXTENSIONS = ('.kt', '.kts')
SCALA_EXTENSIONS = ('.scala', '.sc')
PHP_EXTENSIONS = ('.php',)
DART_EXTENSIONS = ('.dart',)
ELIXIR_EXTENSIONS = ('.ex', '.exs')
LUA_EXTENSIONS = ('.lua',)
ZIG_EXTENSIONS = ('.zig',)
HASKELL_EXTENSIONS = ('.hs',)
R_EXTENSIONS = ('.R', '.r')


# =========================================================================
# Standard library / system module sets
# =========================================================================

PY_STDLIB = frozenset([
    'abc', 'aifc', 'argparse', 'array', 'ast', 'asynchat', 'asyncio',
    'asyncore', 'atexit', 'audioop', 'base64', 'bdb', 'binascii', 'binhex',
    'bisect', 'builtins', 'bz2', 'calendar', 'cgi', 'cgitb', 'chunk',
    'cmath', 'cmd', 'code', 'codecs', 'codeop', 'collections', 'colorsys',
    'compileall', 'concurrent', 'configparser', 'contextlib', 'contextvars',
    'copy', 'copyreg', 'cProfile', 'crypt', 'csv', 'ctypes', 'curses',
    'dataclasses', 'datetime', 'dbm', 'decimal', 'difflib', 'dis',
    'distutils', 'doctest', 'email', 'encodings', 'enum', 'errno',
    'faulthandler', 'fcntl', 'filecmp', 'fileinput', 'fnmatch', 'formatter',
    'fractions', 'ftplib', 'functools', 'gc', 'getopt', 'getpass', 'gettext',
    'glob', 'grp', 'gzip', 'hashlib', 'heapq', 'hmac', 'html', 'http',
    'idlelib', 'imaplib', 'imghdr', 'imp', 'importlib', 'inspect', 'io',
    'ipaddress', 'itertools', 'json', 'keyword', 'lib2to3', 'linecache',
    'locale', 'logging', 'lzma', 'mailbox', 'mailcap', 'marshal', 'math',
    'mimetypes', 'mmap', 'modulefinder', 'multiprocessing', 'netrc', 'nis',
    'nntplib', 'numbers', 'operator', 'optparse', 'os', 'ossaudiodev',
    'parser', 'pathlib', 'pdb', 'pickle', 'pickletools', 'pipes', 'pkgutil',
    'platform', 'plistlib', 'poplib', 'posix', 'posixpath', 'pprint',
    'profile', 'pstats', 'pty', 'pwd', 'py_compile', 'pyclbr', 'pydoc',
    'queue', 'quopri', 'random', 're', 'readline', 'reprlib', 'resource',
    'rlcompleter', 'runpy', 'sched', 'secrets', 'select', 'selectors',
    'shelve', 'shlex', 'shutil', 'signal', 'site', 'smtpd', 'smtplib',
    'sndhdr', 'socket', 'socketserver', 'spwd', 'sqlite3', 'ssl', 'stat',
    'statistics', 'string', 'stringprep', 'struct', 'subprocess', 'sunau',
    'symtable', 'sys', 'sysconfig', 'syslog', 'tabnanny', 'tarfile',
    'telnetlib', 'tempfile', 'termios', 'test', 'textwrap', 'threading',
    'time', 'timeit', 'tkinter', 'token', 'tokenize', 'trace', 'traceback',
    'tracemalloc', 'tty', 'turtle', 'turtledemo', 'types', 'typing',
    'unicodedata', 'unittest', 'urllib', 'uu', 'uuid', 'venv', 'warnings',
    'wave', 'weakref', 'webbrowser', 'winreg', 'winsound', 'wsgiref',
    'xdrlib', 'xml', 'xmlrpc', 'zipapp', 'zipfile', 'zipimport', 'zlib',
    '_thread', '__future__',
])

CS_SYSTEM_PREFIXES = (
    'System', 'Microsoft', 'Windows', 'Internal', 'Interop',
)

SWIFT_SYSTEM_MODULES = frozenset([
    'Foundation', 'UIKit', 'SwiftUI', 'AppKit', 'Combine', 'CoreData',
    'CoreGraphics', 'CoreLocation', 'CoreMotion', 'MapKit', 'Metal',
    'ObjectiveC', 'os', 'Darwin', 'Dispatch', 'XCTest', 'Swift',
    'AVFoundation', 'ARKit', 'CloudKit', 'Contacts', 'CoreBluetooth',
    'CoreImage', 'CoreML', 'CoreMedia', 'CoreText', 'CoreVideo',
    'CryptoKit', 'EventKit', 'GameKit', 'HealthKit', 'HomeKit',
    'IOKit', 'LocalAuthentication', 'MediaPlayer', 'MessageUI',
    'MultipeerConnectivity', 'NaturalLanguage', 'Network', 'NotificationCenter',
    'PassKit', 'Photos', 'QuartzCore', 'RealityKit', 'SafariServices',
    'SceneKit', 'Security', 'SpriteKit', 'StoreKit', 'SystemConfiguration',
    'UserNotifications', 'Vision', 'WatchKit', 'WebKit', 'WidgetKit',
])

KOTLIN_STDLIB_PREFIXES = (
    'kotlin', 'java', 'javax', 'android', 'androidx', 'org.jetbrains',
    'kotlinx',
)

SCALA_STDLIB_PREFIXES = (
    'scala', 'java', 'javax', 'akka', 'play',
)

PHP_SYSTEM_PREFIXES = (
    'Illuminate', 'Symfony', 'Psr', 'Doctrine', 'GuzzleHttp',
    'Monolog', 'Carbon', 'PHPUnit', 'Composer',
)

DART_SYSTEM_PREFIXES = (
    'dart:', 'package:flutter',
)

ELIXIR_STDLIB = frozenset([
    'Kernel', 'Enum', 'List', 'Map', 'String', 'IO', 'File', 'Path',
    'Agent', 'Task', 'GenServer', 'Supervisor', 'Application',
    'Logger', 'Inspect', 'Protocol', 'Stream', 'Range', 'Regex',
    'Tuple', 'Keyword', 'Access', 'Macro', 'Module', 'Process',
    'Port', 'System', 'Code', 'ETS', 'Node', 'Atom', 'Integer',
    'Float', 'Function', 'Exception', 'Collectable', 'Enumerable',
    'MapSet', 'HashSet', 'HashDict', 'Set', 'Dict', 'Base',
    'Bitwise', 'Record', 'URI', 'Calendar', 'Date', 'DateTime',
    'Time', 'NaiveDateTime', 'Version', 'Behaviour', 'GenEvent',
    'ExUnit', 'Mix', 'IEx', 'EEx', 'Plug', 'Phoenix', 'Ecto',
])

RUBY_STDLIB = frozenset([
    'abbrev', 'base64', 'benchmark', 'bigdecimal', 'cgi', 'csv', 'date',
    'dbm', 'debug', 'delegate', 'digest', 'drb', 'English', 'erb', 'etc',
    'expect', 'fcntl', 'fiddle', 'fileutils', 'find', 'forwardable',
    'gdbm', 'getoptlong', 'io/console', 'io/nonblock', 'io/wait', 'ipaddr',
    'irb', 'json', 'logger', 'matrix', 'minitest', 'monitor', 'mutex_m',
    'net/ftp', 'net/http', 'net/imap', 'net/pop', 'net/smtp', 'nkf',
    'objspace', 'observer', 'open-uri', 'open3', 'openssl', 'optparse',
    'ostruct', 'pathname', 'pp', 'prettyprint', 'prime', 'pstore',
    'psych', 'pty', 'racc', 'rake', 'rdoc', 'readline', 'reline',
    'resolv', 'rinda', 'ripper', 'rss', 'rubygems', 'securerandom',
    'set', 'shellwords', 'singleton', 'socket', 'stringio', 'strscan',
    'syslog', 'tempfile', 'time', 'timeout', 'tmpdir', 'tracer',
    'tsort', 'un', 'uri', 'weakref', 'webrick', 'win32ole', 'yaml', 'zlib',
    'bundler', 'rails', 'active_support', 'active_record', 'action_view',
    'action_controller', 'action_mailer', 'active_model', 'active_job',
    'action_cable', 'action_pack', 'sprockets', 'rack', 'puma', 'thin',
    'sinatra', 'rspec', 'nokogiri', 'httparty', 'faraday', 'devise',
])

LUA_STDLIB = frozenset([
    'coroutine', 'debug', 'io', 'math', 'os', 'package', 'string',
    'table', 'utf8', 'bit32', 'bit',
    # Common third-party / engine modules treated as external
    'lfs', 'socket', 'ssl', 'mime', 'ltn12', 'lpeg', 'cjson',
    'love', 'love.audio', 'love.data', 'love.event', 'love.filesystem',
    'love.font', 'love.graphics', 'love.image', 'love.joystick',
    'love.keyboard', 'love.math', 'love.mouse', 'love.physics',
    'love.sound', 'love.system', 'love.thread', 'love.timer',
    'love.touch', 'love.video', 'love.window',
])

ZIG_STDLIB = frozenset([
    'std', 'builtin',
])

HASKELL_STDLIB = frozenset([
    'Prelude', 'Control.Applicative', 'Control.Arrow', 'Control.Category',
    'Control.Concurrent', 'Control.Exception', 'Control.Monad',
    'Control.Monad.IO.Class', 'Control.Monad.Fix', 'Control.Monad.Fail',
    'Control.Monad.ST', 'Control.Monad.Zip',
    'Data.Bits', 'Data.Bool', 'Data.Char', 'Data.Complex', 'Data.Data',
    'Data.Dynamic', 'Data.Either', 'Data.Eq', 'Data.Fixed', 'Data.Foldable',
    'Data.Function', 'Data.Functor', 'Data.IORef', 'Data.Int', 'Data.Ix',
    'Data.Kind', 'Data.List', 'Data.Map', 'Data.Maybe', 'Data.Monoid',
    'Data.Ord', 'Data.Proxy', 'Data.Ratio', 'Data.STRef', 'Data.Semigroup',
    'Data.Sequence', 'Data.Set', 'Data.String', 'Data.Traversable',
    'Data.Tuple', 'Data.Typeable', 'Data.Unique', 'Data.Void', 'Data.Word',
    'Data.ByteString', 'Data.Text', 'Data.Map.Strict', 'Data.Map.Lazy',
    'Data.IntMap', 'Data.IntSet', 'Data.HashMap.Strict', 'Data.HashSet',
    'Data.Vector', 'Data.Aeson', 'Data.Time',
    'Debug.Trace',
    'Foreign', 'Foreign.C', 'Foreign.Marshal', 'Foreign.Ptr',
    'Foreign.StablePtr', 'Foreign.Storable',
    'GHC.Base', 'GHC.Generics', 'GHC.IO', 'GHC.TypeLits',
    'Numeric', 'Numeric.Natural',
    'System.Directory', 'System.Environment', 'System.Exit', 'System.IO',
    'System.Info', 'System.Mem', 'System.Posix', 'System.Process',
    'System.Random', 'System.Timeout',
    'Text.ParserCombinators.ReadP', 'Text.Printf', 'Text.Read',
    'Text.Show', 'Text.Megaparsec', 'Text.Parsec',
    'Network.HTTP', 'Network.Socket', 'Network.URI',
    'Test.HUnit', 'Test.QuickCheck', 'Test.Hspec',
])

# Haskell: top-level module prefixes that indicate stdlib/external
HASKELL_STDLIB_PREFIXES = (
    'Control.', 'Data.', 'Debug.', 'Foreign.', 'GHC.', 'Numeric.',
    'System.', 'Text.', 'Network.', 'Test.',
)

R_STDLIB = frozenset([
    'base', 'compiler', 'datasets', 'grDevices', 'graphics', 'grid',
    'methods', 'parallel', 'splines', 'stats', 'stats4', 'tcltk',
    'tools', 'utils',
    # Common CRAN/external packages treated as external
    'ggplot2', 'dplyr', 'tidyr', 'readr', 'purrr', 'tibble', 'stringr',
    'forcats', 'lubridate', 'tidyverse', 'shiny', 'knitr', 'rmarkdown',
    'devtools', 'testthat', 'roxygen2', 'magrittr', 'rlang', 'glue',
    'httr', 'jsonlite', 'xml2', 'rvest', 'plyr', 'reshape2', 'data.table',
    'caret', 'randomForest', 'xgboost', 'e1071', 'MASS', 'lattice',
    'survival', 'nlme', 'lme4', 'Matrix',
])


# =========================================================================
# Helper functions
# =========================================================================

def collapse_py_multiline_imports(source: str) -> str:
    """Replace parenthesised import lists with single-line equivalents."""
    def _repl(m: Match[str]) -> str:
        prefix = m.group(1)             # "from foo import "
        body = m.group(2)               # "a,\n    b,\n    c\n"
        names = ', '.join(
            n.strip() for n in body.replace('\n', ' ').split(',') if n.strip()
        )
        return prefix + names
    return _PY_MULTILINE_IMPORT_RE.sub(_repl, source)


# =========================================================================
# Resolution cache
# =========================================================================

class ResolutionCache:
    """Per-build cache for import resolution results.

    Resolution functions are called thousands of times with the same arguments
    during a single ``build_graph`` invocation (e.g. many files importing
    ``react`` or ``os``).  This cache stores ``(resolver_name, import_path,
    source_file) → result`` mappings and is discarded between builds so stale
    results never leak across scans.

    Usage::

        cache = ResolutionCache()
        # ... inside the build loop ...
        result = cache.get('js', raw_path, filename)
        if result is None:
            result = resolve_js_import(raw_path, filename, directory, known_files)
            cache.put('js', raw_path, filename, result)
    """

    __slots__ = ('_store',)

    def __init__(self) -> None:
        self._store = {}

    def get(self, resolver: str, import_path: str, source_file: str | None = None) -> object | None:
        return self._store.get((resolver, import_path, source_file))

    def put(self, resolver: str, import_path: str, source_file: str | None, value: object) -> None:
        self._store[(resolver, import_path, source_file)] = value

    def clear(self) -> None:
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)


# =========================================================================
# Resolution functions
# =========================================================================

def resolve_js_import(import_path: str, source_file: str, directory: str, known_files: set[str]) -> tuple[str, bool]:
    """Try to resolve a JS/TS import path to a real file in the project.

    Handles bare specifiers (treated as external / node_modules — skipped when
    hide_system is on), relative paths, and extensionless imports by probing
    common extensions.
    """
    if not import_path.startswith('.'):
        # Bare / absolute specifier — treat like a "system" import
        return import_path, True

    source_dir = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(source_dir, import_path))

    # If already has a known extension, use as-is
    if candidate in known_files:
        return candidate, False

    # Probe common extensions
    for ext in JS_EXTENSIONS:
        probe = candidate + ext
        if probe in known_files:
            return probe, False

    # Probe index files (import './foo' → ./foo/index.js)
    for ext in JS_EXTENSIONS:
        probe = os.path.join(candidate, 'index' + ext)
        if probe in known_files:
            return probe, False

    # Return the raw path — may create an "unresolved" node, which is fine
    return candidate, False


def resolve_py_import(module_path: str, source_file: str, directory: str, known_files: set[str]) -> tuple[str, bool]:
    """Resolve a Python import to a file path.

    *module_path* is the dotted module string (e.g. ``foo.bar`` or ``.bar``
    for relative imports).  Returns ``(resolved_path, is_external)``.
    """
    is_relative = module_path.startswith('.')

    if is_relative:
        # Count leading dots
        dots = len(module_path) - len(module_path.lstrip('.'))
        remainder = module_path.lstrip('.')
        source_dir = os.path.dirname(source_file)
        # Go up (dots - 1) directories from source_dir
        base = source_dir
        for _ in range(dots - 1):
            base = os.path.dirname(base)
        parts = remainder.split('.') if remainder else []
        candidate_dir = os.path.join(base, *parts) if parts else base
    else:
        top_level = module_path.split('.')[0]
        if top_level in PY_STDLIB:
            return module_path, True
        parts = module_path.split('.')
        candidate_dir = os.path.join(*parts)

    # Try as a module file
    candidate_file = candidate_dir + '.py'
    if candidate_file in known_files:
        return candidate_file, False

    # Try as a package __init__.py
    candidate_init = os.path.join(candidate_dir, '__init__.py')
    if candidate_init in known_files:
        return candidate_init, False

    # If it doesn't resolve locally, treat as external
    if not is_relative:
        return module_path, True

    return candidate_file, False


def resolve_java_import(import_path: str, directory: str, known_files: set[str]) -> list[tuple[str, bool]]:
    """Resolve a Java import to source files.

    Returns a list of ``(resolved_path, is_external)`` tuples.
    Wildcard imports expand to all ``.java`` files in the matching directory.
    """
    is_wildcard = import_path.endswith('.*')
    if is_wildcard:
        # com.example.* → com/example/
        pkg = import_path[:-2].replace('.', os.sep)
        matches = [f for f in known_files
                   if f.startswith(pkg + os.sep) and f.endswith('.java')
                   and os.sep not in f[len(pkg) + 1:]]
        if matches:
            return [(m, False) for m in matches]
        return [(import_path, True)]
    else:
        # com.example.Foo → com/example/Foo.java
        candidate = import_path.replace('.', os.sep) + '.java'
        if candidate in known_files:
            return [(candidate, False)]
        return [(import_path, True)]


def parse_go_mod(directory: str) -> str | None:
    """Read go.mod and return the module path, or None."""
    go_mod = os.path.join(directory, 'go.mod')
    if not os.path.isfile(go_mod):
        return None
    with open(go_mod, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if line.startswith('module '):
                return line[len('module '):].strip()
    return None


def resolve_go_import(import_path: str, directory: str, known_files: set[str], module_path: str | None) -> tuple[str, bool]:
    """Resolve a Go import path.

    Returns ``(resolved_path, is_external)``.
    """
    if module_path and import_path.startswith(module_path):
        # Local import: strip module path prefix to get relative path
        rel = import_path[len(module_path):].lstrip('/')
        # A Go import points to a package (directory), find .go files there
        matches = [f for f in known_files
                   if f.startswith(rel + '/') or f.startswith(rel + os.sep)]
        if matches:
            # Return the directory as the node (package-level)
            return rel, False
        return import_path, True
    # Standard library: no dots in path
    if '.' not in import_path.split('/')[0]:
        return import_path, True
    # Third-party
    return import_path, True


def resolve_rust_mod(mod_name: str, source_file: str, directory: str, known_files: set[str]) -> tuple[str, bool]:
    """Resolve a Rust ``mod foo;`` declaration.

    Follows Rust conventions: ``foo.rs`` or ``foo/mod.rs`` relative to the
    declaring file's directory.
    """
    source_dir = os.path.dirname(source_file)
    # Try sibling file
    candidate = os.path.join(source_dir, mod_name + '.rs')
    if candidate in known_files:
        return candidate, False
    # Try directory with mod.rs
    candidate = os.path.join(source_dir, mod_name, 'mod.rs')
    if candidate in known_files:
        return candidate, False
    return os.path.join(source_dir, mod_name + '.rs'), False


def build_cs_namespace_map(directory: str, known_files: set[str]) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Pre-scan .cs files to build a map of declared namespace → [file paths].

    Also builds a class-name → file path map for individual type resolution.
    Returns ``(ns_map, class_map)`` where *ns_map* maps a full namespace string
    to a sorted list of relative file paths and *class_map* maps
    ``Namespace.ClassName`` to the file that likely defines it.
    """
    ns_map = {}   # "MyApp.Models" → ["Models/Order.cs", "Models/User.cs"]
    class_map = {}  # "MyApp.Models.User" → "Models/User.cs"

    for rel_path in known_files:
        if not rel_path.endswith('.cs'):
            continue
        full_path = os.path.join(directory, rel_path)
        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except OSError:
            continue

        for m in CS_NAMESPACE_RE.finditer(content):
            ns = m.group(1)
            ns_map.setdefault(ns, [])
            if rel_path not in ns_map[ns]:
                ns_map[ns].append(rel_path)

            # Map Namespace.FileName (sans extension) → file path
            basename = os.path.splitext(os.path.basename(rel_path))[0]
            class_key = ns + '.' + basename
            class_map[class_key] = rel_path

    # Sort file lists for deterministic output
    for ns in ns_map:
        ns_map[ns] = sorted(ns_map[ns])

    return ns_map, class_map


def resolve_cs_using(namespace: str, directory: str, known_files: set[str], ns_map: dict[str, list[str]] | None = None,
                     class_map: dict[str, str] | None = None) -> tuple[list[str], bool]:
    """Resolve a C# ``using`` directive to project file(s) if possible.

    C# using directives reference namespaces, not files directly.  Resolution
    proceeds in priority order:

    1. **Namespace map** (most reliable) — match against namespaces actually
       declared in the project's ``.cs`` files.
    2. **Path heuristics** — convert namespace segments to path components.
    3. If nothing matches, the namespace is treated as external.

    Returns ``(list_of_resolved_paths, is_external)``.
    """
    # Check for system/framework namespace
    if namespace.startswith(CS_SYSTEM_PREFIXES):
        return [namespace], True

    # --- Strategy 1: namespace map from actual declarations ---
    if ns_map is not None:
        # Exact namespace match
        if namespace in ns_map:
            return ns_map[namespace], False

        # Try as Namespace.ClassName
        if class_map and namespace in class_map:
            return [class_map[namespace]], False

        # Check if this namespace is a parent of any known namespace
        prefix = namespace + '.'
        children = []
        for ns, files in ns_map.items():
            if ns.startswith(prefix) or ns == namespace:
                children.extend(files)
        if children:
            return sorted(set(children)), False

    # --- Strategy 2: path heuristics (fallback) ---
    parts = namespace.split('.')

    def _normalize(s: str) -> str:
        """Normalise a string for fuzzy directory matching."""
        return s.lower().replace('-', '_')

    # Build a normalised lookup of known file directories
    norm_dir_map = {}  # normalised_dir → original_dir
    for f in known_files:
        d = os.path.dirname(f)
        if d:
            norm_dir_map[_normalize(d)] = d

    # 2a. Try to match a specific .cs file
    for start in range(len(parts)):
        for end in range(len(parts), start, -1):
            seg = parts[start:end]
            candidate = os.path.join(*seg) + '.cs'
            if candidate in known_files:
                return [candidate], False
            # Fuzzy: try with hyphens replaced by underscores and vice versa
            candidate_norm = candidate.replace('_', '-')
            if candidate_norm != candidate and candidate_norm in known_files:
                return [candidate_norm], False

    # 2b. Try to match a directory
    for start in range(len(parts)):
        seg = parts[start:]
        candidate_dir = os.path.join(*seg)
        # Exact match
        matches = [f for f in known_files
                   if os.path.dirname(f) == candidate_dir and f.endswith('.cs')]
        if matches:
            return sorted(matches), False
        # Fuzzy match (hyphen ↔ underscore)
        norm_key = _normalize(candidate_dir)
        if norm_key in norm_dir_map:
            real_dir = norm_dir_map[norm_key]
            matches = [f for f in known_files
                       if os.path.dirname(f) == real_dir and f.endswith('.cs')]
            if matches:
                return sorted(matches), False

    # Could not resolve — treat as external
    return [namespace], True


def resolve_swift_import(module_name: str, source_file: str, directory: str, known_files: set[str]) -> tuple[str, bool]:
    """Resolve a Swift import to a local file or mark as external.

    Swift imports reference modules (not files directly).  For local project
    files we try to match the module name to a .swift file or a directory of
    .swift files.

    Returns ``(resolved, is_external)``.
    """
    top_module = module_name.split('.')[0]
    if top_module in SWIFT_SYSTEM_MODULES:
        return module_name, True

    # Try as a .swift file
    candidate = module_name.replace('.', os.sep) + '.swift'
    if candidate in known_files:
        return candidate, False

    # Try as a directory containing .swift files
    dir_path = module_name.replace('.', os.sep)
    matches = [f for f in known_files
               if f.startswith(dir_path + os.sep) and f.endswith('.swift')]
    if matches:
        return dir_path, False

    # Try just the base name
    base = module_name.split('.')[-1] + '.swift'
    for f in known_files:
        if os.path.basename(f) == base:
            return f, False

    return module_name, True


def resolve_ruby_require(req_path: str, source_file: str, directory: str, known_files: set[str], relative: bool = False) -> tuple[str, bool]:
    """Resolve a Ruby require/require_relative to a project file.

    Returns ``(resolved, is_external)``.
    """
    if relative:
        source_dir = os.path.dirname(source_file)
        candidate = os.path.normpath(os.path.join(source_dir, req_path))
    else:
        # Check if it's a stdlib/gem
        top = req_path.split('/')[0]
        if top in RUBY_STDLIB:
            return req_path, True
        candidate = req_path

    # Try with .rb extension
    if not candidate.endswith('.rb'):
        candidate_rb = candidate + '.rb'
    else:
        candidate_rb = candidate

    if candidate_rb in known_files:
        return candidate_rb, False

    # Try without extension
    if candidate in known_files:
        return candidate, False

    # For non-relative requires, it's likely a gem
    if not relative:
        return req_path, True

    return candidate_rb, False


def resolve_kotlin_import(import_path: str, directory: str, known_files: set[str]) -> tuple[str, bool]:
    """Resolve a Kotlin import to source files.

    Returns ``(resolved_path, is_external)``.
    Kotlin imports work like Java — dot-separated packages map to directories.
    """
    # Check for stdlib/system import
    for prefix in KOTLIN_STDLIB_PREFIXES:
        if import_path.startswith(prefix):
            return import_path, True

    is_wildcard = import_path.endswith('.*')
    if is_wildcard:
        pkg = import_path[:-2].replace('.', os.sep)
        matches = [f for f in known_files
                   if f.startswith(pkg + os.sep)
                   and (f.endswith('.kt') or f.endswith('.kts'))
                   and os.sep not in f[len(pkg) + 1:]]
        if matches:
            return matches[0], False
        return import_path, True
    else:
        # com.example.Foo → com/example/Foo.kt
        candidate = import_path.replace('.', os.sep) + '.kt'
        if candidate in known_files:
            return candidate, False
        candidate_kts = import_path.replace('.', os.sep) + '.kts'
        if candidate_kts in known_files:
            return candidate_kts, False
        # Try as a directory package (last segment is a class in a file)
        parts = import_path.split('.')
        if len(parts) >= 2:
            parent_path = os.sep.join(parts[:-1]) + '.kt'
            if parent_path in known_files:
                return parent_path, False
        return import_path, True


def resolve_scala_import(import_path: str, directory: str, known_files: set[str]) -> tuple[str, bool]:
    """Resolve a Scala import to source files.

    Returns ``(resolved_path, is_external)``.
    Handles brace imports like ``com.example.{Foo, Bar}``.
    """
    # Strip brace imports: com.example.{Foo, Bar} → com.example
    base_path = import_path
    if '.{' in import_path:
        base_path = import_path[:import_path.index('.{')]

    # Check for stdlib/system import
    for prefix in SCALA_STDLIB_PREFIXES:
        if base_path.startswith(prefix):
            return import_path, True

    is_wildcard = base_path.endswith('._')
    if is_wildcard:
        base_path = base_path[:-2]

    candidate = base_path.replace('.', os.sep) + '.scala'
    if candidate in known_files:
        return candidate, False
    candidate_sc = base_path.replace('.', os.sep) + '.sc'
    if candidate_sc in known_files:
        return candidate_sc, False
    # Try as directory (package object)
    pkg_obj = os.path.join(base_path.replace('.', os.sep), 'package.scala')
    if pkg_obj in known_files:
        return pkg_obj, False
    # Try parent path (class inside a file)
    parts = base_path.split('.')
    if len(parts) >= 2:
        parent_path = os.sep.join(parts[:-1]) + '.scala'
        if parent_path in known_files:
            return parent_path, False
    return import_path, True


def build_php_namespace_map(directory: str, known_files: set[str]) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Pre-scan .php files to build a map of declared namespace → [file paths].

    Returns ``(ns_map, class_map)`` where *ns_map* maps a full namespace string
    to a sorted list of relative file paths and *class_map* maps
    ``Namespace\\ClassName`` to the file path.
    """
    ns_map = {}
    class_map = {}

    for rel_path in known_files:
        if not rel_path.endswith('.php'):
            continue
        full_path = os.path.join(directory, rel_path)
        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except OSError:
            continue

        for m in PHP_NAMESPACE_RE.finditer(content):
            ns = m.group(1)
            ns_map.setdefault(ns, [])
            if rel_path not in ns_map[ns]:
                ns_map[ns].append(rel_path)

            basename = os.path.splitext(os.path.basename(rel_path))[0]
            class_key = ns + '\\' + basename
            class_map[class_key] = rel_path

    for ns in ns_map:
        ns_map[ns] = sorted(ns_map[ns])

    return ns_map, class_map


def resolve_php_use(namespace: str, directory: str, known_files: set[str], ns_map: dict[str, list[str]] | None = None,
                    class_map: dict[str, str] | None = None) -> tuple[str, bool]:
    """Resolve a PHP ``use`` statement to project file(s) if possible.

    Returns ``(resolved_path, is_external)``.
    """
    # Check for framework/system namespace
    for prefix in PHP_SYSTEM_PREFIXES:
        if namespace.startswith(prefix):
            return namespace, True

    # Strategy 1: namespace/class map
    if class_map and namespace in class_map:
        return class_map[namespace], False

    if ns_map:
        if namespace in ns_map:
            files = ns_map[namespace]
            if files:
                return files[0], False

        prefix = namespace + '\\'
        children = []
        for ns, files in ns_map.items():
            if ns.startswith(prefix) or ns == namespace:
                children.extend(files)
        if children:
            return sorted(set(children))[0], False

    # Strategy 2: path heuristics — convert backslashes to path separators
    candidate = namespace.replace('\\', os.sep) + '.php'
    if candidate in known_files:
        return candidate, False

    # Try mapping to directory structure (PSR-4 style)
    parts = namespace.split('\\')
    for start in range(len(parts)):
        candidate = os.path.join(*parts[start:]) + '.php'
        if candidate in known_files:
            return candidate, False

    return namespace, True


def resolve_php_require(req_path: str, source_file: str, directory: str, known_files: set[str]) -> tuple[str, bool]:
    """Resolve a PHP require/include to a project file.

    Returns ``(resolved_path, is_external)``.
    """
    source_dir = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(source_dir, req_path))

    if candidate in known_files:
        return candidate, False

    # Try from project root
    if req_path in known_files:
        return req_path, False

    return candidate, False


def resolve_dart_import(import_path: str, source_file: str, directory: str, known_files: set[str]) -> tuple[str, bool]:
    """Resolve a Dart import to a project file.

    Returns ``(resolved_path, is_external)``.
    """
    # dart:core, dart:async, etc.
    if import_path.startswith('dart:'):
        return import_path, True

    # package: imports
    if import_path.startswith('package:'):
        # package:my_app/models/user.dart → lib/models/user.dart
        # For external packages, treat as external
        parts = import_path[len('package:'):].split('/', 1)
        if len(parts) == 2:
            pkg_name, rest = parts
            # Check if it matches a local package (lib/ directory)
            candidate = os.path.join('lib', rest)
            if candidate in known_files:
                return candidate, False
        # Check system prefixes
        for prefix in DART_SYSTEM_PREFIXES:
            if import_path.startswith(prefix):
                return import_path, True
        return import_path, True

    # Relative imports
    source_dir = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(source_dir, import_path))
    if candidate in known_files:
        return candidate, False

    # Try from project root
    if import_path in known_files:
        return import_path, False

    return candidate, False


def resolve_elixir_module(module_name: str, source_file: str, directory: str, known_files: set[str]) -> tuple[str, bool]:
    """Resolve an Elixir module reference to a project file.

    Elixir modules map to files via snake_case conversion:
    ``MyApp.Models.User`` → ``lib/my_app/models/user.ex``

    Returns ``(resolved_path, is_external)``.
    """
    top_module = module_name.split('.')[0]
    if top_module in ELIXIR_STDLIB:
        return module_name, True

    # Convert module path to snake_case file path
    parts = module_name.split('.')
    snake_parts = []
    for part in parts:
        # Convert CamelCase to snake_case
        snake = ''
        for i, ch in enumerate(part):
            if ch.isupper() and i > 0 and part[i-1].islower():
                snake += '_'
            snake += ch.lower()
        snake_parts.append(snake)

    # Try lib/ prefix (standard Elixir project layout)
    candidate = os.path.join('lib', *snake_parts) + '.ex'
    if candidate in known_files:
        return candidate, False

    candidate_exs = os.path.join('lib', *snake_parts) + '.exs'
    if candidate_exs in known_files:
        return candidate_exs, False

    # Try without lib/ prefix
    candidate = os.path.join(*snake_parts) + '.ex'
    if candidate in known_files:
        return candidate, False

    candidate_exs = os.path.join(*snake_parts) + '.exs'
    if candidate_exs in known_files:
        return candidate_exs, False

    # Try just the last part (filename match)
    base = snake_parts[-1]
    for f in known_files:
        fname = os.path.splitext(os.path.basename(f))[0]
        if fname == base and (f.endswith('.ex') or f.endswith('.exs')):
            return f, False

    return module_name, True


def resolve_lua_require(req_path: str, source_file: str, directory: str, known_files: set[str]) -> tuple[str, bool]:
    """Resolve a Lua ``require("module")`` to a project file.

    Lua's ``require`` uses dot-separated module paths that map to directories
    (e.g. ``require("models.user")`` → ``models/user.lua``).

    Returns ``(resolved_path, is_external)``.
    """
    # Check stdlib / well-known external modules
    top = req_path.split('.')[0]
    if top in LUA_STDLIB or req_path in LUA_STDLIB:
        return req_path, True

    # Convert dot-separated path to filesystem path
    candidate = req_path.replace('.', os.sep) + '.lua'
    if candidate in known_files:
        return candidate, False

    # Try init.lua (package-style: models/init.lua)
    init_candidate = os.path.join(req_path.replace('.', os.sep), 'init.lua')
    if init_candidate in known_files:
        return init_candidate, False

    # Try relative to source file
    source_dir = os.path.dirname(source_file)
    rel_candidate = os.path.normpath(os.path.join(source_dir, candidate))
    if rel_candidate in known_files:
        return rel_candidate, False

    # Try as bare filename
    bare = req_path + '.lua'
    if bare in known_files:
        return bare, False

    return req_path, True


def resolve_zig_import(import_path: str, source_file: str, directory: str, known_files: set[str]) -> tuple[str, bool]:
    """Resolve a Zig ``@import("file.zig")`` to a project file.

    Zig imports reference files directly (``@import("file.zig")``) or the
    standard library (``@import("std")``).

    Returns ``(resolved_path, is_external)``.
    """
    # Check stdlib
    if import_path in ZIG_STDLIB:
        return import_path, True

    # Direct file reference — resolve relative to source file
    source_dir = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(source_dir, import_path))
    if candidate in known_files:
        return candidate, False

    # Try from project root
    if import_path in known_files:
        return import_path, False

    # Try adding .zig extension if not present
    if not import_path.endswith('.zig'):
        probe = candidate + '.zig'
        if probe in known_files:
            return probe, False
        probe_root = import_path + '.zig'
        if probe_root in known_files:
            return probe_root, False

    return import_path, True


def resolve_haskell_import(module_name: str, source_file: str, directory: str, known_files: set[str]) -> tuple[str, bool]:
    """Resolve a Haskell ``import Module.Name`` to a project file.

    Haskell modules map to files via path conversion:
    ``Data.Models.User`` → ``Data/Models/User.hs``

    Returns ``(resolved_path, is_external)``.
    """
    # Check stdlib by exact match
    if module_name in HASKELL_STDLIB:
        return module_name, True

    # Check stdlib by prefix
    for prefix in HASKELL_STDLIB_PREFIXES:
        if module_name.startswith(prefix):
            return module_name, True

    # Check single-word well-known module
    if module_name == 'Prelude':
        return module_name, True

    # Convert module path to filesystem path
    candidate = module_name.replace('.', os.sep) + '.hs'
    if candidate in known_files:
        return candidate, False

    # Try src/ prefix (common Haskell project layout)
    src_candidate = os.path.join('src', candidate)
    if src_candidate in known_files:
        return src_candidate, False

    # Try lib/ prefix
    lib_candidate = os.path.join('lib', candidate)
    if lib_candidate in known_files:
        return lib_candidate, False

    # Try app/ prefix (stack projects)
    app_candidate = os.path.join('app', candidate)
    if app_candidate in known_files:
        return app_candidate, False

    # Try just the last component as a filename
    base = module_name.split('.')[-1] + '.hs'
    for f in known_files:
        if os.path.basename(f) == base:
            return f, False

    return module_name, True


def resolve_r_source(source_path: str, source_file: str, directory: str, known_files: set[str]) -> tuple[str, bool]:
    """Resolve an R ``source("file.R")`` to a project file.

    Returns ``(resolved_path, is_external)``.
    """
    # Resolve relative to source file
    source_dir = os.path.dirname(source_file)
    candidate = os.path.normpath(os.path.join(source_dir, source_path))
    if candidate in known_files:
        return candidate, False

    # Try from project root
    if source_path in known_files:
        return source_path, False

    return candidate, False
