"""
SymbolResolver

Executes the 6-step scoped resolution hierarchy to resolve RawRelationship AST edges
into persistent CodeRelationship entities.
"""

from uuid import UUID

from app.parser.models import CodeSymbol
from app.relationships.models import (
    CodeRelationship,
    RawRelationship,
    ResolutionStatus,
)

KNOWN_EXTERNAL_PREFIXES = (
    "os",
    "sys",
    "math",
    "typing",
    "collections",
    "dataclasses",
    "enum",
    "uuid",
    "datetime",
    "asyncio",
    "sqlalchemy",
    "alembic",
    "pytest",
    "tree_sitter",
    "pydantic",
    "fastapi",
)


class SymbolResolver:
    """
    Language-agnostic symbol resolution engine.
    """

    def resolve_relationships(
        self,
        repository_id: UUID,
        file_id: UUID,
        raw_relationships: list[RawRelationship],
        symbols_by_id: dict[UUID, CodeSymbol],
        symbols_by_qualname: dict[str, CodeSymbol],
        symbols_by_name: dict[str, list[CodeSymbol]],
        file_symbols: list[CodeSymbol] | None = None,
    ) -> list[CodeRelationship]:
        """
        Resolve a list of RawRelationship instances into CodeRelationship entities.
        """
        # Map source line to source symbol for attaching source_symbol_id
        source_symbols_by_line: dict[int, CodeSymbol] = {}
        if file_symbols:
            for sym in file_symbols:
                for line in range(sym.start_line, sym.end_line + 1):
                    # Outer / enclosing symbol precedence if multiple
                    if line not in source_symbols_by_line:
                        source_symbols_by_line[line] = sym

        resolved_list: list[CodeRelationship] = []

        for raw in raw_relationships:
            source_symbol = source_symbols_by_line.get(raw.source_line)
            source_symbol_id = source_symbol.id if source_symbol else None
            source_qualname = (
                source_symbol.qualified_name
                if source_symbol and source_symbol.qualified_name
                else raw.source_qualified_name
            )

            target_symbol, status = self.resolve_single_target(
                target_name=raw.target_name,
                target_module_hint=raw.target_module_hint,
                source_qualified_name=source_qualname,
                symbols_by_qualname=symbols_by_qualname,
                symbols_by_name=symbols_by_name,
            )

            code_rel = CodeRelationship(
                repository_id=repository_id,
                file_id=file_id,
                source_symbol_id=source_symbol_id,
                source_scope=raw.source_scope,
                source_qualified_name=source_qualname,
                source_line=raw.source_line,
                source_column=raw.source_column,
                target_symbol_id=target_symbol.id if target_symbol else None,
                target_name=raw.target_name,
                target_module_hint=raw.target_module_hint,
                kind=raw.kind,
                status=status,
                metadata=raw.metadata,
            )
            resolved_list.append(code_rel)

        return resolved_list

    def resolve_single_target(
        self,
        target_name: str,
        target_module_hint: str | None,
        source_qualified_name: str | None,
        symbols_by_qualname: dict[str, CodeSymbol],
        symbols_by_name: dict[str, list[CodeSymbol]],
    ) -> tuple[CodeSymbol | None, ResolutionStatus]:
        """
        Execute 6-step resolution cascade for a single target name.
        """
        # Step 1: Exact qualified_name match
        if target_name in symbols_by_qualname:
            return symbols_by_qualname[target_name], ResolutionStatus.RESOLVED

        # Step 2: Local lexical scope match
        if source_qualified_name:
            # Check parent scopes (e.g. module.Class.method -> module.Class -> module)
            parts = source_qualified_name.split(".")
            while parts:
                scope_prefix = ".".join(parts)
                candidate_qualname = f"{scope_prefix}.{target_name}"
                if candidate_qualname in symbols_by_qualname:
                    return symbols_by_qualname[candidate_qualname], ResolutionStatus.RESOLVED
                parts.pop()

        # Step 3: Import binding / module resolution
        if target_module_hint:
            module_candidate = f"{target_module_hint}.{target_name}"
            if module_candidate in symbols_by_qualname:
                return symbols_by_qualname[module_candidate], ResolutionStatus.RESOLVED

        # Step 4: Repository qualified-name lookup (suffix match)
        target_suffix = f".{target_name}"
        for qualname, sym in symbols_by_qualname.items():
            if qualname.endswith(target_suffix):
                return sym, ResolutionStatus.RESOLVED

        # Step 5: Repository short-name lookup
        if target_name in symbols_by_name and symbols_by_name[target_name]:
            # Pick first matching symbol
            return symbols_by_name[target_name][0], ResolutionStatus.RESOLVED

        # Step 6: External / Unresolved fallback
        is_external = False
        if target_module_hint:
            root_pkg = target_module_hint.split(".")[0]
            if root_pkg in KNOWN_EXTERNAL_PREFIXES:
                is_external = True
        elif target_name.split(".")[0] in KNOWN_EXTERNAL_PREFIXES:
            is_external = True

        status = ResolutionStatus.EXTERNAL if is_external else ResolutionStatus.UNRESOLVED
        return None, status
