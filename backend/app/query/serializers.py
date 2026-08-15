"""
Query DTO Serializers

Provides JSON-compatible dict serialization and deserialization for Phase 4 Query Engine DTOs.
"""

from typing import Any
from uuid import UUID

from app.parser.models import SymbolKind
from app.parser.modifiers import Modifier
from app.parser.types import AttributeInfo, ParameterInfo, ParameterKind
from app.parser.visibility import Visibility
from app.query.models import (
    GraphTraversalResult,
    RelationshipEdgeResult,
    RepositoryContext,
    SymbolResult,
)
from app.relationships.models import RelationshipKind, ResolutionStatus
from app.repository.language import Language


def symbol_result_to_dict(res: SymbolResult) -> dict[str, Any]:
    return {
        "id": str(res.id),
        "file_id": str(res.file_id),
        "repository_id": str(res.repository_id),
        "name": res.name,
        "kind": res.kind.value,
        "language": res.language.value,
        "file_path": res.file_path,
        "start_line": res.start_line,
        "end_line": res.end_line,
        "start_column": res.start_column,
        "end_column": res.end_column,
        "start_byte": res.start_byte,
        "end_byte": res.end_byte,
        "qualified_name": res.qualified_name,
        "parent_symbol_id": str(res.parent_symbol_id) if res.parent_symbol_id else None,
        "parent_kind": res.parent_kind.value if res.parent_kind else None,
        "parent_name": res.parent_name,
        "parameters": [
            {
                "name": p.name,
                "kind": p.kind.value,
                "type_annotation": p.type_annotation,
                "default_value": p.default_value,
            }
            for p in res.parameters
        ],
        "return_type": res.return_type,
        "documentation": res.documentation,
        "visibility": res.visibility.value,
        "modifiers": [m.value for m in res.modifiers],
        "attributes": [{"name": a.name, "arguments": a.arguments} for a in res.attributes],
        "base_classes": res.base_classes,
        "metadata": res.metadata,
    }


def symbol_result_from_dict(d: dict[str, Any]) -> SymbolResult:
    return SymbolResult(
        id=UUID(d["id"]),
        file_id=UUID(d["file_id"]),
        repository_id=UUID(d["repository_id"]),
        name=d["name"],
        kind=SymbolKind(d["kind"]),
        language=Language(d["language"]),
        file_path=d["file_path"],
        start_line=d["start_line"],
        end_line=d["end_line"],
        start_column=d["start_column"],
        end_column=d["end_column"],
        start_byte=d["start_byte"],
        end_byte=d["end_byte"],
        qualified_name=d.get("qualified_name"),
        parent_symbol_id=UUID(d["parent_symbol_id"]) if d.get("parent_symbol_id") else None,
        parent_kind=SymbolKind(d["parent_kind"]) if d.get("parent_kind") else None,
        parent_name=d.get("parent_name"),
        parameters=[
            ParameterInfo(
                name=p["name"],
                kind=ParameterKind(p["kind"]),
                type_annotation=p.get("type_annotation"),
                default_value=p.get("default_value"),
            )
            for p in d.get("parameters", [])
        ],
        return_type=d.get("return_type"),
        documentation=d.get("documentation"),
        visibility=Visibility(d.get("visibility", "unknown")),
        modifiers={
            Modifier(m) for m in d.get("modifiers", []) if m in Modifier.__members__.values()
        },
        attributes=[
            AttributeInfo(name=a["name"], arguments=a.get("arguments", []))
            for a in d.get("attributes", [])
        ],
        base_classes=d.get("base_classes", []),
        metadata=d.get("metadata", {}),
    )


def relationship_edge_to_dict(edge: RelationshipEdgeResult) -> dict[str, Any]:
    return {
        "id": str(edge.id),
        "repository_id": str(edge.repository_id),
        "file_id": str(edge.file_id),
        "kind": edge.kind.value,
        "status": edge.status.value,
        "target_name": edge.target_name,
        "source_symbol_id": str(edge.source_symbol_id) if edge.source_symbol_id else None,
        "source_scope": edge.source_scope,
        "source_qualified_name": edge.source_qualified_name,
        "source_line": edge.source_line,
        "source_column": edge.source_column,
        "target_symbol_id": str(edge.target_symbol_id) if edge.target_symbol_id else None,
        "target_module_hint": edge.target_module_hint,
        "metadata": edge.metadata,
    }


def relationship_edge_from_dict(d: dict[str, Any]) -> RelationshipEdgeResult:
    return RelationshipEdgeResult(
        id=UUID(d["id"]),
        repository_id=UUID(d["repository_id"]),
        file_id=UUID(d["file_id"]),
        kind=RelationshipKind(d["kind"]),
        status=ResolutionStatus(d["status"]),
        target_name=d["target_name"],
        source_symbol_id=UUID(d["source_symbol_id"]) if d.get("source_symbol_id") else None,
        source_scope=d.get("source_scope"),
        source_qualified_name=d.get("source_qualified_name"),
        source_line=d.get("source_line", 0),
        source_column=d.get("source_column"),
        target_symbol_id=UUID(d["target_symbol_id"]) if d.get("target_symbol_id") else None,
        target_module_hint=d.get("target_module_hint"),
        metadata=d.get("metadata", {}),
    )


def repository_context_to_dict(ctx: RepositoryContext) -> dict[str, Any]:
    return {
        "repository_id": str(ctx.repository_id),
        "primary_symbols": [symbol_result_to_dict(s) for s in ctx.primary_symbols],
        "related_symbols": [symbol_result_to_dict(s) for s in ctx.related_symbols],
        "relationships": [relationship_edge_to_dict(e) for e in ctx.relationships],
        "relevant_files": ctx.relevant_files,
        "metadata": ctx.metadata,
    }


def repository_context_from_dict(d: dict[str, Any]) -> RepositoryContext:
    return RepositoryContext(
        repository_id=UUID(d["repository_id"]),
        primary_symbols=[symbol_result_from_dict(s) for s in d.get("primary_symbols", [])],
        related_symbols=[symbol_result_from_dict(s) for s in d.get("related_symbols", [])],
        relationships=[relationship_edge_from_dict(e) for e in d.get("relationships", [])],
        relevant_files=d.get("relevant_files", []),
        metadata=d.get("metadata", {}),
    )


def graph_traversal_to_dict(res: GraphTraversalResult) -> dict[str, Any]:
    return {
        "root_symbol_id": str(res.root_symbol_id),
        "max_depth": res.max_depth,
        "nodes": {str(k): symbol_result_to_dict(v) for k, v in res.nodes.items()},
        "edges": [relationship_edge_to_dict(e) for e in res.edges],
    }


def graph_traversal_from_dict(d: dict[str, Any]) -> GraphTraversalResult:
    return GraphTraversalResult(
        root_symbol_id=UUID(d["root_symbol_id"]),
        max_depth=d["max_depth"],
        nodes={UUID(k): symbol_result_from_dict(v) for k, v in d.get("nodes", {}).items()},
        edges=[relationship_edge_from_dict(e) for e in d.get("edges", [])],
    )
