from enum import Enum


class Visibility(str, Enum):
    UNKNOWN = "unknown"
    PUBLIC = "public"
    PRIVATE = "private"
    PROTECTED = "protected"
    INTERNAL = "internal"
    PACKAGE = "package"
