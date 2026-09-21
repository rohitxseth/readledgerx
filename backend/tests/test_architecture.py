"""
Services depend only on Protocols, and concrete classes are constructed in
exactly one place, the composition root. These check the source so the claims
in the README stay true.
"""

import ast
from pathlib import Path

from app.interfaces.client_interfaces import IBookIntelligence
from app.services.book_intelligence import BookIntelligenceService

APP = Path(__file__).resolve().parents[1] / "app"
COMPOSITION_ROOT = APP / "core" / "dependencies.py"

# Modules whose classes are implementations that services must not name.
CONCRETE = ("app.repositories", "app.integrations", "app.services.book_intelligence")

# Implementations that live outside repositories/ and integrations/, plus the
# factory that builds the LLM client.
_OTHER_IMPLEMENTATIONS = {
    "BookIntelligenceService",
    "BcryptPasswordHasher",
    "TokenService",
    "get_langchain_llm",
}


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text())


def _imports(path: Path) -> set[str]:
    return {
        node.module
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.ImportFrom) and node.module
    }


def _calls(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _implementations() -> set[str]:
    defined = {
        node.name
        for package in ("repositories", "integrations")
        for path in (APP / package).glob("*.py")
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.ClassDef)
    }
    return defined | _OTHER_IMPLEMENTATIONS


def test_services_import_no_concrete_dependencies():
    offenders = {
        f"{path.name} imports {module}"
        for path in (APP / "services").glob("*.py")
        for module in _imports(path)
        if module.startswith(CONCRETE) and path.stem != "book_intelligence"
    }
    assert offenders == set()


def test_only_the_composition_root_constructs_implementations():
    implementations = _implementations()
    assert {"UserRepository", "GoogleBooksClient"} <= implementations  # sanity

    offenders = {
        f"{path.relative_to(APP)} calls {name}()"
        for path in APP.rglob("*.py")
        if path != COMPOSITION_ROOT
        for name in _calls(path) & implementations
    }
    assert offenders == set()


def test_book_intelligence_satisfies_its_protocol():
    assert isinstance(BookIntelligenceService(llm=None), IBookIntelligence)
