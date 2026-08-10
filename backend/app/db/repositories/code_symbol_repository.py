"""
Repository for persisting and querying code symbols.
"""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CodeSymbolORM
from app.parser.models import CodeSymbol


class CodeSymbolRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    @staticmethod
    def _to_orm(symbol: CodeSymbol) -> CodeSymbolORM:
        return CodeSymbolORM(
            id=symbol.id,
            file_id=symbol.file.id,
            parent_symbol_id=symbol.parent_symbol_id,
            name=symbol.name,
            qualified_name=symbol.qualified_name,
            kind=symbol.kind.value,
            return_type=symbol.return_type,
            documentation=symbol.documentation,
            visibility=symbol.visibility.value,
            parameters=[
                {
                    "name": parameter.name,
                    "kind": parameter.kind.value,
                    "type_annotation": parameter.type_annotation,
                    "default_value": parameter.default_value,
                }
                for parameter in symbol.parameters
            ],
            attributes=[
                {
                    "name": attribute.name,
                    "arguments": attribute.arguments,
                }
                for attribute in symbol.attributes
            ],
            modifiers=[modifier.value for modifier in symbol.modifiers],
            base_classes=symbol.base_classes,
            metadata_json=symbol.metadata,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            start_column=symbol.start_column,
            end_column=symbol.end_column,
            start_byte=symbol.start_byte,
            end_byte=symbol.end_byte,
        )

    async def bulk_create(
        self,
        symbols: list[CodeSymbol],
    ) -> None:
        if not symbols:
            return

        orm_symbols = [self._to_orm(symbol) for symbol in symbols]

        self._session.add_all(orm_symbols)
        await self._session.flush()

    async def get_by_file(
        self,
        file_id: UUID,
    ) -> list[CodeSymbolORM]:
        result = await self._session.scalars(
            select(CodeSymbolORM)
            .where(CodeSymbolORM.file_id == file_id)
            .order_by(CodeSymbolORM.start_line)
        )
        return list(result)

    async def delete_by_file(
        self,
        file_id: UUID,
    ) -> None:
        if not file_id:
            return

        await self._session.execute(delete(CodeSymbolORM).where(CodeSymbolORM.file_id == file_id))

    async def delete_by_file_ids(
        self,
        file_ids: list[UUID],
    ) -> None:
        if not file_ids:
            return

        await self._session.execute(
            delete(CodeSymbolORM).where(CodeSymbolORM.file_id.in_(file_ids))
        )
