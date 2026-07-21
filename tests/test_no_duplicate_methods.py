"""
Guard against silently-overwritten methods.

Python allows a class to define the same method name twice; the later
definition simply replaces the earlier one, with no warning.  This bit
us once: MainWindow grew two `_on_restore` methods (timeline restore and
backup restore), and the timeline's Restore button quietly started
opening the backup file dialog.

This test parses every module in the package and fails, with file and
line numbers, if any class defines a method name twice.
"""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "wordvault"


def test_no_class_defines_a_method_twice():
    problems = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                seen = {}
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name in seen:
                            problems.append(
                                f"{path.name}:{item.lineno} "
                                f"{node.name}.{item.name} silently overwrites "
                                f"the definition at line {seen[item.name]}"
                            )
                        seen[item.name] = item.lineno
    assert not problems, "\n".join(problems)
