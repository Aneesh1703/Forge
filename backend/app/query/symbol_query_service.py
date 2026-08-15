"""
SymbolQueryService

Executes rich structured queries against PostgreSQL for symbol discovery and lookups.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.code_symbol_orm import CodeSymbolORM
from app.db.models.repository_file_orm import RepositoryFileORM
from app.parser.models import SymbolKind
from app.parser.modifiers import Modifier
from app.parser.types import AttributeInfo, ParameterInfo, ParameterKind
from app.parser.visibility import Visibility
from app.query.models import SymbolQueryFilter, SymbolResult
from app.repository.language import Language


class SymbolQueryService:
    """
    Service for querying code symbols in a repository.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    @staticmethod
    def _to_result(orm: CodeSymbolORM, file_orm: RepositoryFileORM | None = None) -> SymbolResult:
        file_path = ""
        repo_id = UUID("00000000-0000-0000-0000-000000000000")
        lang = Language.PYTHON

        target_file = file_orm or (orm.file if hasattr(orm, "file") and orm.file else None)
        if target_file:
            file_path = target_file.relative_path
            repo_id = target_file.repository_id
            try:
                lang = Language(target_file.language)
            except ValueError:
                lang = Language.PYTHON

        # Convert parameters
        raw_params = orm.parameters or []
        params: list[ParameterInfo] = []
        for p in raw_params:
            if isinstance(p, dict):
                p_kind = ParameterKind.UNKNOWN
                if "kind" in p and p["kind"]:
                    try:
                        p_kind = ParameterKind(p["kind"])
                    except ValueError:
                        p_kind = ParameterKind.UNKNOWN
                params.append(
                    ParameterInfo(
                        name=p.get("name", ""),
                        kind=p_kind,
                        type_annotation=p.get("type_annotation") or p.get("type"),
                        default_value=p.get("default_value"),
                    )
                )
            elif isinstance(p, ParameterInfo):
                params.append(p)

        # Convert attributes
        raw_attrs = orm.attributes or []
        attrs: list[AttributeInfo] = []
        for a in raw_attrs:
            if isinstance(a, dict):
                attrs.append(
                    AttributeInfo(
                        name=a.get("name", ""),
                        arguments=a.get("arguments") or [],
                    )
                )
            elif isinstance(a, AttributeInfo):
                attrs.append(a)

        # Convert modifiers
        raw_mods = orm.modifiers or []
        modifiers = {Modifier(m) for m in raw_mods if m in Modifier.__members__.values()}

        # Visibility
        try:
            vis = Visibility(orm.visibility)
        except ValueError:
            vis = Visibility.UNKNOWN

        # Kind
        try:
            kind = SymbolKind(orm.kind)
        except ValueError:
            kind = SymbolKind.UNKNOWN

        parent_kind = None
        parent_name = None
        if hasattr(orm, "parent") and orm.parent:
            try:
                parent_kind = SymbolKind(orm.parent.kind)
            except ValueError:
                parent_kind = SymbolKind.UNKNOWN
            parent_name = orm.parent.name

        return SymbolResult(
            id=orm.id,
            file_id=orm.file_id,
            repository_id=repo_id,
            name=orm.name,
            kind=kind,
            language=lang,
            file_path=file_path,
            start_line=orm.start_line,
            end_line=orm.end_line,
            start_column=orm.start_column,
            end_column=orm.end_column,
            start_byte=orm.start_byte,
            end_byte=orm.end_byte,
            qualified_name=orm.qualified_name,
            parent_symbol_id=orm.parent_symbol_id,
            parent_kind=parent_kind,
            parent_name=parent_name,
            parameters=params,
            return_type=orm.return_type,
            documentation=orm.documentation,
            visibility=vis,
            modifiers=modifiers,
            attributes=attrs,
            base_classes=orm.base_classes or [],
            metadata=orm.metadata_json or {},
        )

    async def search_symbols(
        self,
        repo_id: UUID,
        filter_options: SymbolQueryFilter,
    ) -> list[SymbolResult]:
        """
        Execute structured search for symbols based on SymbolQueryFilter.
        """
        query = (
            select(CodeSymbolORM)
            .join(RepositoryFileORM, CodeSymbolORM.file_id == RepositoryFileORM.id)
            .where(RepositoryFileORM.repository_id == repo_id)
            .options(selectinload(CodeSymbolORM.file), selectinload(CodeSymbolORM.parent))
        )

        if filter_options.name:
            query = query.where(CodeSymbolORM.name == filter_options.name)
        elif filter_options.name_prefix:
            query = query.where(CodeSymbolORM.name.startswith(filter_options.name_prefix))

        if filter_options.qualified_name:
            query = query.where(CodeSymbolORM.qualified_name == filter_options.qualified_name)
        elif filter_options.qualified_name_prefix:
            query = query.where(
                CodeSymbolORM.qualified_name.startswith(filter_options.qualified_name_prefix)
            )

        if filter_options.kinds:
            kind_values = [
                k.value if isinstance(k, SymbolKind) else str(k) for k in filter_options.kinds
            ]
            query = query.where(CodeSymbolORM.kind.in_(kind_values))

        if filter_options.file_id:
            query = query.where(CodeSymbolORM.file_id == filter_options.file_id)

        if filter_options.language:
            lang_str = (
                filter_options.language.value
                if isinstance(filter_options.language, Language)
                else str(filter_options.language)
            )
            query = query.where(RepositoryFileORM.language == lang_str)

        if filter_options.visibility:
            vis_str = (
                filter_options.visibility.value
                if isinstance(filter_options.visibility, Visibility)
                else str(filter_options.visibility)
            )
            query = query.where(CodeSymbolORM.visibility == vis_str)

        if filter_options.parent_symbol_id:
            query = query.where(CodeSymbolORM.parent_symbol_id == filter_options.parent_symbol_id)

        if filter_options.documentation_contains:
            query = query.where(
                CodeSymbolORM.documentation.ilike(f"%{filter_options.documentation_contains}%")
            )

        query = query.offset(filter_options.offset).limit(filter_options.limit)

        result = await self._session.scalars(query)
        symbols_orm = list(result)

        # Filter modifiers or annotations in Python if set
        results: list[SymbolResult] = []
        for sym_orm in symbols_orm:
            sym_res = self._to_result(sym_orm)
            if filter_options.modifiers:
                if not filter_options.modifiers.issubset(sym_res.modifiers):
                    continue
            if filter_options.annotation:
                has_ann = any(
                    attr.name == filter_options.annotation or filter_options.annotation in attr.name
                    for attr in sym_res.attributes
                )
                if not has_ann:
                    continue
            results.append(sym_res)

        return results

    async def find_by_qualified_name(
        self,
        repo_id: UUID,
        qualified_name: str,
    ) -> SymbolResult | None:
        """
        Find a single symbol by its exact qualified name.
        """
        query = (
            select(CodeSymbolORM)
            .join(RepositoryFileORM, CodeSymbolORM.file_id == RepositoryFileORM.id)
            .where(
                RepositoryFileORM.repository_id == repo_id,
                CodeSymbolORM.qualified_name == qualified_name,
            )
            .options(selectinload(CodeSymbolORM.file), selectinload(CodeSymbolORM.parent))
            .limit(1)
        )
        result = await self._session.scalar(query)
        return self._to_result(result) if result else None

    async def find_by_file(
        self,
        file_id: UUID,
    ) -> list[SymbolResult]:
        """
        Find all symbols defined inside a specific file.
        """
        query = (
            select(CodeSymbolORM)
            .where(CodeSymbolORM.file_id == file_id)
            .options(selectinload(CodeSymbolORM.file), selectinload(CodeSymbolORM.parent))
            .order_by(CodeSymbolORM.start_line)
        )
        result = await self._session.scalars(query)
        return [self._to_result(sym) for sym in result]

    async def find_children(
        self,
        symbol_id: UUID,
    ) -> list[SymbolResult]:
        """
        Find all direct child symbols (e.g. methods inside a class, nested functions).
        """
        query = (
            select(CodeSymbolORM)
            .where(CodeSymbolORM.parent_symbol_id == symbol_id)
            .options(selectinload(CodeSymbolORM.file), selectinload(CodeSymbolORM.parent))
            .order_by(CodeSymbolORM.start_line)
        )
        result = await self._session.scalars(query)
        return [self._to_result(sym) for sym in result]

    async def find_parent(
        self,
        symbol_id: UUID,
    ) -> SymbolResult | None:
        """
        Find the direct parent symbol of a given symbol.
        """
        child_query = select(CodeSymbolORM.parent_symbol_id).where(CodeSymbolORM.id == symbol_id)
        parent_id = await self._session.scalar(child_query)
        if not parent_id:
            return None

        parent_query = (
            select(CodeSymbolORM)
            .where(CodeSymbolORM.id == parent_id)
            .options(selectinload(CodeSymbolORM.file), selectinload(CodeSymbolORM.parent))
        )
        parent_orm = await self._session.scalar(parent_query)
        return self._to_result(parent_orm) if parent_orm else None
