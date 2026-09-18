"""Bindings and global references in the notebook planner's generated cells."""

import ast
import symtable
import textwrap


class _Bindings(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.names.add(node.id)

    def visit_Import(self, node: ast.Import | ast.ImportFrom) -> None:
        self.names.update(
            alias.asname or alias.name.split(".")[0] for alias in node.names
        )

    visit_ImportFrom = visit_Import

    def visit_FunctionDef(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ) -> None:
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def visit_comprehension(self, node: ast.comprehension) -> None:
        # Iterators are private even when Python 3.12+ inlines the comprehension.
        self.visit(node.iter)
        for condition in node.ifs:
            self.visit(condition)


def _references(table: symtable.SymbolTable) -> set[str]:
    names = {
        symbol.get_name()
        for symbol in table.get_symbols()
        if symbol.is_referenced() and symbol.is_global()
    }
    for child in table.get_children():
        names.update(_references(child))
    return names


def scope(source: str) -> tuple[frozenset[str], frozenset[str]]:
    bindings = _Bindings()
    bindings.visit(ast.parse(source))
    definitions = {name for name in bindings.names if not name.startswith("_")}
    # Cells execute as functions; module symbol tables expose inlined iterator locals.
    cell = "def _cell():\n" + textwrap.indent(
        source if source.strip() else "pass", "    "
    )
    table = symtable.symtable(cell, "<notebook>", "exec")
    references = _references(
        next(child for child in table.get_children() if child.get_name() == "_cell")
    )
    return frozenset(definitions), frozenset(references)
