"""
Services depend only on Protocols; concrete classes are named in exactly one
place, the composition root. This checks the import graph so the claim in the
README stays true.
"""

import ast
from pathlib import Path

from app.interfaces.client_interfaces import IBookIntelligence
from app.services.book_intelligence import BookIntelligenceService

APP = Path(__file__).resolve().parents[1] / "app"

# Modules whose classes are implementations that services must not name.
CONCRETE = ("app.repositories", "app.integrations", "app.services.book_intelligence")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }


def test_services_import_no_concrete_dependencies():
    offenders = {
        f"{path.name} imports {module}"
        for path in (APP / "services").glob("*.py")
        for module in _imports(path)
        if module.startswith(CONCRETE) and path.stem != "book_intelligence"
    }
    assert offenders == set()


def test_book_intelligence_satisfies_its_protocol():
    assert isinstance(BookIntelligenceService(llm=None), IBookIntelligence)
