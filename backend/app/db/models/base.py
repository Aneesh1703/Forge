"""
DeclarativeBase

↓

RepositoryORM

RepositoryFileORM

CodeSymbolORM
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass
    __abstract__ = True
