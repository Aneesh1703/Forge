"""
SemanticChunkBuilder

Generates hierarchical, retrievable semantic code chunks (Levels 1–5)
consuming Phase 4 Query Engine APIs.
"""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.chunks.models import ChunkType, CodeChunk
from app.db.models.code_relationship_orm import CodeRelationshipORM
from app.db.models.code_symbol_orm import CodeSymbolORM
from app.db.models.repository_file_orm import RepositoryFileORM
from app.parser.models import SymbolKind
from app.query.context_builder import RepositoryContextBuilder
from app.query.graph_query_service import GraphQueryService
from app.query.impact_query_service import ImpactQueryService
from app.query.models import SymbolResult
from app.query.symbol_query_service import SymbolQueryService
from app.repository.language import Language


class SemanticChunkBuilder:
    """
    Engine for transforming Phase 1–4 structured repository knowledge into hierarchical CodeChunks.
    """

    def __init__(self, session: AsyncSession):
        self._session = session
        self._symbol_service = SymbolQueryService(session)
        self._graph_service = GraphQueryService(session)
        self._impact_service = ImpactQueryService(session)
        self._context_builder = RepositoryContextBuilder(session)

    async def build_symbol_chunks(
        self,
        symbol_id: UUID,
        source_code: str | None = None,
    ) -> list[CodeChunk]:
        """
        Build Level 1 (Symbol Chunk) and Level 2 (Contextual Symbol Chunk) for a given symbol.
        """
        sym = await self._get_symbol_result(symbol_id)
        if not sym:
            return []

        chunks: list[CodeChunk] = []

        # Code snippet extraction
        code_snippet = source_code or ""

        # Level 1: Symbol Chunk
        l1_content = self._format_level1_content(sym, code_snippet)
        l1_chunk = CodeChunk.create(
            repository_id=sym.repository_id,
            file_id=sym.file_id,
            symbol_id=sym.id,
            chunk_type=ChunkType.SYMBOL,
            content=l1_content,
            symbol_name=sym.name,
            qualified_name=sym.qualified_name,
            language=sym.language,
            file_path=sym.file_path,
            start_line=sym.start_line,
            end_line=sym.end_line,
            metadata={"level": 1, "kind": sym.kind.value},
        )
        chunks.append(l1_chunk)

        # Level 2: Contextual Symbol Chunk
        related_syms = await self._context_builder.get_related_symbols(symbol_id, depth=1)
        l2_content = self._format_level2_content(sym, code_snippet, related_syms)
        l2_chunk = CodeChunk.create(
            repository_id=sym.repository_id,
            file_id=sym.file_id,
            symbol_id=sym.id,
            chunk_type=ChunkType.CONTEXTUAL_SYMBOL,
            content=l2_content,
            symbol_name=sym.name,
            qualified_name=sym.qualified_name,
            language=sym.language,
            file_path=sym.file_path,
            start_line=sym.start_line,
            end_line=sym.end_line,
            metadata={"level": 2, "related_count": len(related_syms)},
        )
        chunks.append(l2_chunk)

        return chunks

    async def build_class_summary_chunk(
        self,
        class_symbol_id: UUID,
    ) -> CodeChunk | None:
        """
        Build Level 3 (Class Summary Chunk) for class symbols.
        """
        sym = await self._get_symbol_result(class_symbol_id)
        if not sym or sym.kind != SymbolKind.CLASS:
            return None

        children = await self._symbol_service.find_children(class_symbol_id)
        methods = [c for c in children if c.kind == SymbolKind.METHOD]

        lines: list[str] = [
            f"Class: {sym.qualified_name or sym.name}",
            f"File: {sym.file_path} (Lines {sym.start_line}-{sym.end_line})",
            f"Language: {sym.language.value}",
        ]
        if sym.documentation:
            lines.extend(["", "Documentation:", sym.documentation])

        if sym.base_classes:
            lines.extend(["", f"Base Classes: {', '.join(sym.base_classes)}"])

        if methods:
            lines.extend(["", "Methods:"])
            for m in methods:
                params_str = ", ".join([p.name for p in m.parameters])
                ret_str = f" -> {m.return_type}" if m.return_type else ""
                lines.append(f"- {m.name}({params_str}){ret_str}")

        content = "\n".join(lines)
        return CodeChunk.create(
            repository_id=sym.repository_id,
            file_id=sym.file_id,
            symbol_id=sym.id,
            chunk_type=ChunkType.CLASS_SUMMARY,
            content=content,
            symbol_name=sym.name,
            qualified_name=sym.qualified_name,
            language=sym.language,
            file_path=sym.file_path,
            start_line=sym.start_line,
            end_line=sym.end_line,
            metadata={"level": 3, "method_count": len(methods)},
        )

    async def build_file_overview_chunk(
        self,
        file_id: UUID,
    ) -> CodeChunk | None:
        """
        Build Level 4 (File Overview Chunk) summarizing all symbols and imports in a file.
        """
        file_orm = await self._session.get(RepositoryFileORM, file_id)
        if not file_orm:
            return None

        symbols = await self._symbol_service.find_by_file(file_id)
        imports = await self._graph_service.get_imports(file_id)

        try:
            lang = Language(file_orm.language)
        except ValueError:
            lang = Language.PYTHON

        lines: list[str] = [
            f"File: {file_orm.relative_path}",
            f"Language: {file_orm.language}",
            f"Size: {file_orm.size} bytes",
            "",
            "Contains Symbols:",
        ]
        if symbols:
            for s in symbols:
                lines.append(
                    f"- {s.name} (Kind: {s.kind.value}, Lines: {s.start_line}-{s.end_line})"
                )
        else:
            lines.append("- (No symbols extracted)")

        if imports:
            lines.extend(["", "Module Imports:"])
            for imp in imports:
                lines.append(f"- {imp.target_name}")

        content = "\n".join(lines)
        return CodeChunk.create(
            repository_id=file_orm.repository_id,
            file_id=file_orm.id,
            symbol_id=None,
            chunk_type=ChunkType.FILE_OVERVIEW,
            content=content,
            language=lang,
            file_path=file_orm.relative_path,
            start_line=1,
            end_line=max(1, len(symbols)),
            metadata={
                "level": 4,
                "symbol_count": len(symbols),
                "import_count": len(imports),
            },
        )

    async def build_graph_context_chunk(
        self,
        symbol_id: UUID,
    ) -> CodeChunk | None:
        """
        Build Level 5 (Graph / Impact Context Chunk) for AI change impact queries.
        """
        impact = await self._impact_service.get_impact_analysis(symbol_id, depth=2)
        if not impact:
            return None

        sym = impact.target_symbol
        lines: list[str] = [
            f"Symbol Impact Context: {sym.qualified_name or sym.name}",
            f"File: {sym.file_path}",
            "",
            "Direct Callers:",
        ]
        if impact.direct_callers:
            for c in impact.direct_callers:
                lines.append(f"- {c.qualified_name or c.name} (File: {c.file_path})")
        else:
            lines.append("- None")

        if impact.dependent_types:
            lines.extend(["", "Dependent Types:"])
            for t in impact.dependent_types:
                lines.append(f"- {t.qualified_name or t.name} (File: {t.file_path})")

        if impact.subclasses:
            lines.extend(["", "Subclasses:"])
            for sub in impact.subclasses:
                lines.append(f"- {sub.qualified_name or sub.name} (File: {sub.file_path})")

        lines.extend(["", "Affected File Paths:"])
        for p in impact.affected_file_paths:
            lines.append(f"- {p}")

        content = "\n".join(lines)
        return CodeChunk.create(
            repository_id=sym.repository_id,
            file_id=sym.file_id,
            symbol_id=sym.id,
            chunk_type=ChunkType.GRAPH_CONTEXT,
            content=content,
            symbol_name=sym.name,
            qualified_name=sym.qualified_name,
            language=sym.language,
            file_path=sym.file_path,
            start_line=sym.start_line,
            end_line=sym.end_line,
            metadata={
                "level": 5,
                "direct_callers_count": len(impact.direct_callers),
                "affected_files_count": len(impact.affected_file_paths),
            },
        )

    async def build_all_chunks_for_file(
        self,
        file_id: UUID,
    ) -> list[CodeChunk]:
        """
        Bulk generate all hierarchical chunks (Levels 1–5) for a file.
        """
        chunks: list[CodeChunk] = []

        # Level 4 file overview
        file_ov = await self.build_file_overview_chunk(file_id)
        if file_ov:
            chunks.append(file_ov)

        symbols = await self._symbol_service.find_by_file(file_id)
        for sym in symbols:
            # Levels 1 & 2
            sym_chunks = await self.build_symbol_chunks(sym.id)
            chunks.extend(sym_chunks)

            # Level 3 (Class Summary)
            if sym.kind == SymbolKind.CLASS:
                cls_chunk = await self.build_class_summary_chunk(sym.id)
                if cls_chunk:
                    chunks.append(cls_chunk)

            # Level 5 (Graph Context for functions/methods)
            if sym.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD, SymbolKind.CLASS):
                grp_chunk = await self.build_graph_context_chunk(sym.id)
                if grp_chunk:
                    chunks.append(grp_chunk)

        return chunks

    async def build_all_chunks_for_repository(
        self,
        repo_id: UUID,
    ) -> list[CodeChunk]:
        """
        Bulk generate hierarchical chunks for an entire repository in O(1) database queries.
        Prefetches all files, symbols, and relationships upfront into memory maps.
        """
        # Query 1: Fetch all files in repo
        files = (
            await self._session.scalars(
                select(RepositoryFileORM).where(RepositoryFileORM.repository_id == repo_id)
            )
        ).all()
        if not files:
            return []

        file_map = {f.id: f for f in files}
        file_ids = list(file_map.keys())

        # Query 2: Fetch all symbols in repo (with loaded file and parent)
        symbols_orm = (
            await self._session.scalars(
                select(CodeSymbolORM)
                .where(CodeSymbolORM.file_id.in_(file_ids))
                .options(
                    selectinload(CodeSymbolORM.file),
                    selectinload(CodeSymbolORM.parent),
                )
            )
        ).all()

        # Query 3: Fetch all relationships in repo
        rels_orm = (
            await self._session.scalars(
                select(CodeRelationshipORM).where(CodeRelationshipORM.repository_id == repo_id)
            )
        ).all()

        # Build in-memory representations & lookup tables
        symbols_by_id: dict[UUID, SymbolResult] = {}
        symbols_by_file: dict[UUID, list[SymbolResult]] = defaultdict(list)
        children_by_parent: dict[UUID, list[SymbolResult]] = defaultdict(list)

        for s_orm in symbols_orm:
            if not s_orm.file:
                continue
            sym_res = SymbolQueryService._to_result(s_orm)
            symbols_by_id[sym_res.id] = sym_res
            symbols_by_file[sym_res.file_id].append(sym_res)
            if s_orm.parent_symbol_id:
                children_by_parent[s_orm.parent_symbol_id].append(sym_res)

        imports_by_file: dict[UUID, list[str]] = defaultdict(list)
        callers_by_symbol: dict[UUID, list[SymbolResult]] = defaultdict(list)
        subclasses_by_symbol: dict[UUID, list[SymbolResult]] = defaultdict(list)
        uses_type_by_symbol: dict[UUID, list[SymbolResult]] = defaultdict(list)

        for r in rels_orm:
            if r.kind == "imports":
                imports_by_file[r.file_id].append(r.target_name)
            elif r.target_symbol_id and r.source_symbol_id:
                src_sym = symbols_by_id.get(r.source_symbol_id)
                if src_sym:
                    if r.kind == "calls":
                        callers_by_symbol[r.target_symbol_id].append(src_sym)
                    elif r.kind == "inherits":
                        subclasses_by_symbol[r.target_symbol_id].append(src_sym)
                    elif r.kind == "uses_type":
                        uses_type_by_symbol[r.target_symbol_id].append(src_sym)

        all_chunks: list[CodeChunk] = []

        for file_orm in files:
            fid = file_orm.id
            file_symbols = symbols_by_file.get(fid, [])
            file_imports = imports_by_file.get(fid, [])

            try:
                lang = Language(file_orm.language)
            except ValueError:
                lang = Language.PYTHON

            # Level 4 File Overview Chunk
            lines: list[str] = [
                f"File: {file_orm.relative_path}",
                f"Language: {file_orm.language}",
                f"Size: {file_orm.size} bytes",
                "",
                "Contains Symbols:",
            ]
            if file_symbols:
                for s in file_symbols:
                    lines.append(
                        f"- {s.name} (Kind: {s.kind.value}, Lines: {s.start_line}-{s.end_line})"
                    )
            else:
                lines.append("- (No symbols extracted)")

            if file_imports:
                lines.extend(["", "Module Imports:"])
                for imp in file_imports:
                    lines.append(f"- {imp}")

            l4_content = "\n".join(lines)
            all_chunks.append(
                CodeChunk.create(
                    repository_id=file_orm.repository_id,
                    file_id=file_orm.id,
                    symbol_id=None,
                    chunk_type=ChunkType.FILE_OVERVIEW,
                    content=l4_content,
                    language=lang,
                    file_path=file_orm.relative_path,
                    start_line=1,
                    end_line=max(1, len(file_symbols)),
                    metadata={
                        "level": 4,
                        "symbol_count": len(file_symbols),
                        "import_count": len(file_imports),
                    },
                )
            )

            for sym in file_symbols:
                # Level 1 Symbol Chunk
                l1_content = self._format_level1_content(sym, "")
                all_chunks.append(
                    CodeChunk.create(
                        repository_id=sym.repository_id,
                        file_id=sym.file_id,
                        symbol_id=sym.id,
                        chunk_type=ChunkType.SYMBOL,
                        content=l1_content,
                        symbol_name=sym.name,
                        qualified_name=sym.qualified_name,
                        language=sym.language,
                        file_path=sym.file_path,
                        start_line=sym.start_line,
                        end_line=sym.end_line,
                        metadata={"level": 1, "kind": sym.kind.value},
                    )
                )

                # Level 2 Contextual Symbol Chunk
                related = callers_by_symbol.get(sym.id, [])
                l2_content = self._format_level2_content(sym, "", related)
                all_chunks.append(
                    CodeChunk.create(
                        repository_id=sym.repository_id,
                        file_id=sym.file_id,
                        symbol_id=sym.id,
                        chunk_type=ChunkType.CONTEXTUAL_SYMBOL,
                        content=l2_content,
                        symbol_name=sym.name,
                        qualified_name=sym.qualified_name,
                        language=sym.language,
                        file_path=sym.file_path,
                        start_line=sym.start_line,
                        end_line=sym.end_line,
                        metadata={"level": 2, "related_count": len(related)},
                    )
                )

                # Level 3 Class Summary Chunk
                if sym.kind == SymbolKind.CLASS:
                    children = children_by_parent.get(sym.id, [])
                    methods = [c for c in children if c.kind == SymbolKind.METHOD]
                    c_lines = [
                        f"Class: {sym.qualified_name or sym.name}",
                        f"File: {sym.file_path} (Lines {sym.start_line}-{sym.end_line})",
                        f"Language: {sym.language.value}",
                    ]
                    if sym.documentation:
                        c_lines.extend(["", "Documentation:", sym.documentation])
                    if sym.base_classes:
                        c_lines.extend(
                            [
                                "",
                                f"Base Classes: {', '.join(sym.base_classes)}",
                            ]
                        )
                    if methods:
                        c_lines.extend(["", "Methods:"])
                        for m in methods:
                            params_str = ", ".join([p.name for p in m.parameters])
                            ret_str = f" -> {m.return_type}" if m.return_type else ""
                            c_lines.append(f"- {m.name}({params_str}){ret_str}")

                    all_chunks.append(
                        CodeChunk.create(
                            repository_id=sym.repository_id,
                            file_id=sym.file_id,
                            symbol_id=sym.id,
                            chunk_type=ChunkType.CLASS_SUMMARY,
                            content="\n".join(c_lines),
                            symbol_name=sym.name,
                            qualified_name=sym.qualified_name,
                            language=sym.language,
                            file_path=sym.file_path,
                            start_line=sym.start_line,
                            end_line=sym.end_line,
                            metadata={
                                "level": 3,
                                "method_count": len(methods),
                            },
                        )
                    )

                # Level 5 Graph Context Chunk
                if sym.kind in (
                    SymbolKind.FUNCTION,
                    SymbolKind.METHOD,
                    SymbolKind.CLASS,
                ):
                    direct_callers = callers_by_symbol.get(sym.id, [])
                    dependent_types = uses_type_by_symbol.get(sym.id, [])
                    subclasses = subclasses_by_symbol.get(sym.id, [])
                    affected_files = list(
                        {
                            c.file_path
                            for c in direct_callers + dependent_types + subclasses
                            if c.file_path
                        }
                    )

                    g_lines = [
                        f"Symbol Impact Context: {sym.qualified_name or sym.name}",
                        f"File: {sym.file_path}",
                        "",
                        "Direct Callers:",
                    ]
                    if direct_callers:
                        for c in direct_callers:
                            g_lines.append(f"- {c.qualified_name or c.name} (File: {c.file_path})")
                    else:
                        g_lines.append("- None")

                    if dependent_types:
                        g_lines.extend(["", "Dependent Types:"])
                        for t in dependent_types:
                            g_lines.append(f"- {t.qualified_name or t.name} (File: {t.file_path})")

                    if subclasses:
                        g_lines.extend(["", "Subclasses:"])
                        for sub in subclasses:
                            g_lines.append(
                                f"- {sub.qualified_name or sub.name} (File: {sub.file_path})"
                            )

                    g_lines.extend(["", "Affected File Paths:"])
                    for p in affected_files:
                        g_lines.append(f"- {p}")

                    all_chunks.append(
                        CodeChunk.create(
                            repository_id=sym.repository_id,
                            file_id=sym.file_id,
                            symbol_id=sym.id,
                            chunk_type=ChunkType.GRAPH_CONTEXT,
                            content="\n".join(g_lines),
                            symbol_name=sym.name,
                            qualified_name=sym.qualified_name,
                            language=sym.language,
                            file_path=sym.file_path,
                            start_line=sym.start_line,
                            end_line=sym.end_line,
                            metadata={
                                "level": 5,
                                "direct_callers_count": len(direct_callers),
                                "affected_files_count": len(affected_files),
                            },
                        )
                    )

        return all_chunks

    async def _get_symbol_result(self, symbol_id: UUID) -> SymbolResult | None:
        query = (
            select(CodeSymbolORM)
            .where(CodeSymbolORM.id == symbol_id)
            .options(selectinload(CodeSymbolORM.file), selectinload(CodeSymbolORM.parent))
        )
        orm = await self._session.scalar(query)
        return SymbolQueryService._to_result(orm) if orm else None

    @staticmethod
    def _format_level1_content(sym: SymbolResult, source_code: str) -> str:
        lines = [
            f"Symbol: {sym.qualified_name or sym.name}",
            f"Kind: {sym.kind.value} | Language: {sym.language.value}",
            f"File: {sym.file_path} (Lines {sym.start_line}-{sym.end_line})",
        ]
        if sym.documentation:
            lines.extend(["", "Documentation:", sym.documentation])

        if sym.parameters:
            params_str = ", ".join(
                [f"{p.name}: {p.type_annotation or 'Any'}" for p in sym.parameters]
            )
            lines.extend(["", f"Parameters: {params_str}"])

        if sym.return_type:
            lines.append(f"Returns: {sym.return_type}")

        if source_code:
            lines.extend(["", "Code:", source_code])

        return "\n".join(lines)

    @staticmethod
    def _format_level2_content(
        sym: SymbolResult,
        source_code: str,
        related_syms: list[SymbolResult],
    ) -> str:
        base_content = SemanticChunkBuilder._format_level1_content(sym, source_code)
        if not related_syms:
            return base_content

        related_lines = ["", "Related Context:"]
        for r in related_syms[:5]:
            related_lines.append(f"- {r.name} (Kind: {r.kind.value}, File: {r.file_path})")

        return base_content + "\n" + "\n".join(related_lines)
