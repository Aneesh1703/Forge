from enum import Enum


class Modifier(str, Enum):
    ASYNC = "async"
    GENERATOR = "generator"
    STATIC = "static"
    PROPERTY = "property"
    ABSTRACT = "abstract"
    FINAL = "final"
    SEALED = "sealed"
    READONLY = "readonly"
