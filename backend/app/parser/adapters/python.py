"""Create PythonAdapter

Algorithm

1. Look up node.type in NODE_KIND_MAP.

2. If node type is not supported

       return None

3. Determine symbol kind.

4. If symbol is a function

       Check parents.

       If parent is a class

            Change kind to METHOD.

5. Locate the "name" child node.

6. Read symbol name from source.

7. Find enclosing parent symbol
       (class/function/module if applicable).

8. Create SymbolMetadata

9. Return SymbolMetadata."""

from types import MappingProxyType
from uuid import UUID

from tree_sitter import Node

from app.parser.adapters.base import BaseLanguageAdapter
from app.parser.models import (
    ParentSymbol,
    SymbolKind,
    SymbolMetadata,
)
from app.parser.modifiers import Modifier
from app.parser.types import AttributeInfo, ParameterInfo, ParameterKind
from app.parser.visibility import Visibility
from app.relationships.models import RawRelationship, RelationshipKind


class PythonAdapter(BaseLanguageAdapter):
    """
    Language adapter for Python Tree-sitter AST nodes.

    Responsible for converting Python-specific AST nodes into
    generic SymbolMetadata objects understood by Forge.
    """

    NODE_KIND_MAP = MappingProxyType(
        {
            "class_definition": SymbolKind.CLASS,
            "function_definition": SymbolKind.FUNCTION,
        }
    )

    def extract_symbol(
        self,
        node: Node,
        source: bytes,
    ) -> SymbolMetadata | None:
        """
        Extract symbol metadata from a Python AST node.

        Returns None if the node does not represent a supported symbol.
        """

        symbol_kind = self.NODE_KIND_MAP.get(node.type)

        if symbol_kind is None:
            return None

        parent = self._find_parent(node, source)

        # Functions defined inside classes are methods.
        if (
            symbol_kind == SymbolKind.FUNCTION
            and parent is not None
            and parent.kind == SymbolKind.CLASS
        ):
            symbol_kind = SymbolKind.METHOD

        name = self._extract_name(node, source)

        if not name:
            return None

        parameters = []
        if symbol_kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
            parameters = self._extract_parameters(node, source)

        return_type = self._extract_return_type(node, source)
        documentation = self._extract_documentation(node, source)
        attributes = self._extract_attributes(node, source)
        modifiers = self._extract_modifiers(node, source, attributes)
        visibility = self._extract_visibility(name)
        base_classes = self._extract_base_classes(node, source)

        return SymbolMetadata(
            kind=symbol_kind,
            name=name,
            parent=parent,
            parameters=parameters,
            return_type=return_type,
            documentation=documentation,
            attributes=attributes,
            modifiers=modifiers,
            visibility=visibility,
            base_classes=base_classes,
        )

    def _extract_name(
        self,
        node: Node,
        source: bytes,
    ) -> str:
        """
        Extract the identifier name from a symbol node.
        """

        name_node = node.child_by_field_name("name")

        if name_node is None:
            return ""

        return source[name_node.start_byte : name_node.end_byte].decode("utf-8").strip()

    def _find_parent(
        self,
        node: Node,
        source: bytes,
    ) -> ParentSymbol | None:
        """
        Find the nearest enclosing symbol.
        """

        parent = node.parent

        while parent is not None:
            if parent.type == "class_definition":
                return ParentSymbol(
                    kind=SymbolKind.CLASS,
                    name=self._extract_name(parent, source),
                )

            if parent.type == "function_definition":
                return ParentSymbol(
                    kind=SymbolKind.FUNCTION,
                    name=self._extract_name(parent, source),
                )

            parent = parent.parent

        return None

    def _extract_return_type(
        self,
        node: Node,
        source: bytes,
    ) -> str | None:
        """Extract the return type annotation of a function or method."""
        if node.type != "function_definition":
            return None

        return_type_node = node.child_by_field_name("return_type")
        if return_type_node is None:
            return None

        return (
            source[return_type_node.start_byte : return_type_node.end_byte].decode("utf-8").strip()
        )

    def _extract_documentation(
        self,
        node: Node,
        source: bytes,
    ) -> str | None:
        """Extract docstring documentation from a class or function block."""
        body_node = node.child_by_field_name("body")
        if body_node is None:
            return None

        first_stmt = None
        for child in body_node.children:
            if child.type in ("comment", "indent", "newline", "whitespace"):
                continue
            first_stmt = child
            break

        if first_stmt is None:
            return None

        string_node = None
        if first_stmt.type in ("string", "concatenated_string"):
            string_node = first_stmt
        elif first_stmt.type == "expression_statement" and first_stmt.children:
            if first_stmt.children[0].type in ("string", "concatenated_string"):
                string_node = first_stmt.children[0]

        if string_node is None:
            return None

        raw_doc = source[string_node.start_byte : string_node.end_byte].decode("utf-8").strip()

        for prefix in ("r", "f", "rf", "fr", "u", "b"):
            if raw_doc.lower().startswith(prefix):
                raw_doc = raw_doc[len(prefix) :]
                break

        for triple in ('"""', "'''"):
            if raw_doc.startswith(triple) and raw_doc.endswith(triple) and len(raw_doc) >= 6:
                return raw_doc[3:-3].strip()

        for single in ('"', "'"):
            if raw_doc.startswith(single) and raw_doc.endswith(single) and len(raw_doc) >= 2:
                return raw_doc[1:-1].strip()

        return raw_doc

    def _extract_attributes(
        self,
        node: Node,
        source: bytes,
    ) -> list[AttributeInfo]:
        """Extract decorators as AttributeInfo objects."""
        parent = node.parent
        if parent is None or parent.type != "decorated_definition":
            return []

        attributes: list[AttributeInfo] = []

        for child in parent.children:
            if child.type == "decorator":
                dec_expr = None
                for c in child.children:
                    if c.type != "@":
                        dec_expr = c
                        break

                if dec_expr is None:
                    continue

                if dec_expr.type == "call":
                    fn_node = dec_expr.child_by_field_name("function") or (
                        dec_expr.children[0] if dec_expr.children else None
                    )
                    args_node = dec_expr.child_by_field_name("arguments")

                    name = (
                        source[fn_node.start_byte : fn_node.end_byte].decode("utf-8").strip()
                        if fn_node
                        else ""
                    )

                    args: list[str] = []
                    if args_node is not None:
                        for arg_child in args_node.children:
                            if arg_child.type not in ("(", ")", ",", "whitespace"):
                                arg_str = (
                                    source[arg_child.start_byte : arg_child.end_byte]
                                    .decode("utf-8")
                                    .strip()
                                )
                                if arg_str:
                                    args.append(arg_str)

                    if name:
                        attributes.append(AttributeInfo(name=name, arguments=args))

                else:
                    name = source[dec_expr.start_byte : dec_expr.end_byte].decode("utf-8").strip()
                    if name:
                        attributes.append(AttributeInfo(name=name, arguments=[]))

        return attributes

    def _has_yield_expression(self, node: Node) -> bool:
        """Check recursively if a node contains a yield statement/expression."""
        if node.type in ("yield", "yield_expression"):
            return True
        for child in node.children:
            if child.type in ("function_definition", "class_definition"):
                continue
            if self._has_yield_expression(child):
                return True
        return False

    def _extract_modifiers(
        self,
        node: Node,
        source: bytes,
        attributes: list[AttributeInfo],
    ) -> set[Modifier]:
        """Extract universal Modifier enum set for Python functions/classes."""
        modifiers: set[Modifier] = set()

        if node.type == "function_definition":
            for child in node.children[:2]:
                if child.type == "async" or source[child.start_byte : child.end_byte] == b"async":
                    modifiers.add(Modifier.ASYNC)
                    break

            body = node.child_by_field_name("body")
            if body is not None and self._has_yield_expression(body):
                modifiers.add(Modifier.GENERATOR)

        for attr in attributes:
            name = attr.name
            if name == "staticmethod":
                modifiers.add(Modifier.STATIC)
            elif name == "property" or name.endswith((".setter", ".getter", ".deleter")):
                modifiers.add(Modifier.PROPERTY)
            elif name == "abstractmethod" or name.endswith(".abstractmethod"):
                modifiers.add(Modifier.ABSTRACT)
            elif name == "final" or name.endswith(".final"):
                modifiers.add(Modifier.FINAL)

        return modifiers

    def _extract_visibility(self, name: str) -> Visibility:
        """Determine symbol visibility based on Python naming conventions."""
        if name.startswith("__") and not name.endswith("__"):
            return Visibility.PRIVATE
        if name.startswith("_") and not name.startswith("__"):
            return Visibility.PROTECTED
        return Visibility.PUBLIC

    def _extract_base_classes(
        self,
        node: Node,
        source: bytes,
    ) -> list[str]:
        """Extract superclass names for class definitions."""
        if node.type != "class_definition":
            return []

        superclasses_node = node.child_by_field_name(
            "superclasses"
        ) or self._find_first_child_of_type(node, "argument_list")

        if superclasses_node is None:
            return []

        base_classes: list[str] = []
        for child in superclasses_node.children:
            if child.type in ("(", ")", ",", "comment", "whitespace"):
                continue
            base_str = source[child.start_byte : child.end_byte].decode("utf-8").strip()
            if base_str:
                base_classes.append(base_str)

        return base_classes

    def _find_first_child_of_type(
        self,
        node: Node,
        child_type: str,
    ) -> Node | None:
        """Find the first immediate child of a node matching child_type."""
        for child in node.children:
            if child.type == child_type:
                return child
        return None

    def _extract_single_parameter(
        self,
        node: Node,
        source: bytes,
    ) -> ParameterInfo | None:
        """
        Extract ParameterInfo from a single Tree-sitter parameter node.
        """
        if node.type == "identifier":
            name = source[node.start_byte : node.end_byte].decode("utf-8").strip()
            return ParameterInfo(
                name=name,
                kind=ParameterKind.POSITIONAL_OR_KEYWORD,
            )

        if node.type == "typed_parameter":
            name_node = node.child_by_field_name("name") or self._find_first_child_of_type(
                node, "identifier"
            )
            type_node = node.child_by_field_name("type")

            if name_node is None:
                return None

            name = source[name_node.start_byte : name_node.end_byte].decode("utf-8").strip()
            type_annotation = (
                source[type_node.start_byte : type_node.end_byte].decode("utf-8").strip()
                if type_node
                else None
            )

            return ParameterInfo(
                name=name,
                kind=ParameterKind.POSITIONAL_OR_KEYWORD,
                type_annotation=type_annotation,
            )

        if node.type == "default_parameter":
            name_node = node.child_by_field_name("name") or self._find_first_child_of_type(
                node, "identifier"
            )
            value_node = node.child_by_field_name("value")

            if name_node is None:
                return None

            name = source[name_node.start_byte : name_node.end_byte].decode("utf-8").strip()
            default_value = (
                source[value_node.start_byte : value_node.end_byte].decode("utf-8").strip()
                if value_node
                else None
            )

            return ParameterInfo(
                name=name,
                kind=ParameterKind.POSITIONAL_OR_KEYWORD,
                default_value=default_value,
            )

        if node.type == "typed_default_parameter":
            name_node = node.child_by_field_name("name") or self._find_first_child_of_type(
                node, "identifier"
            )
            type_node = node.child_by_field_name("type")
            value_node = node.child_by_field_name("value")

            if name_node is None:
                return None

            name = source[name_node.start_byte : name_node.end_byte].decode("utf-8").strip()
            type_annotation = (
                source[type_node.start_byte : type_node.end_byte].decode("utf-8").strip()
                if type_node
                else None
            )
            default_value = (
                source[value_node.start_byte : value_node.end_byte].decode("utf-8").strip()
                if value_node
                else None
            )

            return ParameterInfo(
                name=name,
                kind=ParameterKind.POSITIONAL_OR_KEYWORD,
                type_annotation=type_annotation,
                default_value=default_value,
            )

        if node.type in ("list_splat", "list_splat_pattern"):
            name_node = node.child_by_field_name("name") or self._find_first_child_of_type(
                node, "identifier"
            )
            type_node = node.child_by_field_name("type")

            if name_node is None:
                return None

            name = source[name_node.start_byte : name_node.end_byte].decode("utf-8").strip()
            type_annotation = (
                source[type_node.start_byte : type_node.end_byte].decode("utf-8").strip()
                if type_node
                else None
            )

            return ParameterInfo(
                name=name,
                kind=ParameterKind.VAR_POSITIONAL,
                type_annotation=type_annotation,
            )

        if node.type in ("dictionary_splat", "dictionary_splat_pattern"):
            name_node = node.child_by_field_name("name") or self._find_first_child_of_type(
                node, "identifier"
            )
            type_node = node.child_by_field_name("type")

            if name_node is None:
                return None

            name = source[name_node.start_byte : name_node.end_byte].decode("utf-8").strip()
            type_annotation = (
                source[type_node.start_byte : type_node.end_byte].decode("utf-8").strip()
                if type_node
                else None
            )

            return ParameterInfo(
                name=name,
                kind=ParameterKind.VAR_KEYWORD,
                type_annotation=type_annotation,
            )

        return None

    def _extract_parameters(
        self,
        node: Node,
        source: bytes,
    ) -> list[ParameterInfo]:
        """
        Extract parameters from a function AST node, taking into account positional (/)
        and keyword (*) separators to classify parameters appropriately.
        """
        params_node = node.child_by_field_name("parameters")

        if params_node is None:
            return []

        parameters: list[ParameterInfo] = []
        current_default_kind = ParameterKind.POSITIONAL_OR_KEYWORD

        for child in params_node.children:
            if child.type in ("/", "positional_separator"):
                for param in parameters:
                    if param.kind == ParameterKind.POSITIONAL_OR_KEYWORD:
                        param.kind = ParameterKind.POSITIONAL_ONLY
                continue

            if child.type in ("*", "keyword_separator"):
                current_default_kind = ParameterKind.KEYWORD_ONLY
                continue

            param_info = self._extract_single_parameter(child, source)

            if param_info is not None:
                if param_info.kind == ParameterKind.POSITIONAL_OR_KEYWORD:
                    param_info.kind = current_default_kind

                if param_info.kind == ParameterKind.VAR_POSITIONAL:
                    current_default_kind = ParameterKind.KEYWORD_ONLY

                parameters.append(param_info)

        return parameters

    def extract_relationships(
        self,
        node: Node,
        source: bytes,
        file_id: UUID,
        start_line: int = 1,
        start_column: int = 0,
        current_symbol: SymbolMetadata | None = None,
        scope: str | None = None,
        qualified_name: str | None = None,
    ) -> list[RawRelationship]:
        """
        Extract raw relationships (INHERITS, IMPORTS, CALLS, USES_TYPE) from Python AST node.
        """
        relationships: list[RawRelationship] = []
        source_line = start_line
        source_column = start_column
        symbol_name = current_symbol.name if current_symbol else None

        if node.type == "class_definition":
            base_classes = self._extract_base_classes(node, source)
            for base in base_classes:
                relationships.append(
                    RawRelationship(
                        source_file_id=file_id,
                        target_name=base,
                        kind=RelationshipKind.INHERITS,
                        source_line=source_line,
                        source_column=source_column,
                        source_symbol_name=symbol_name,
                        source_scope=scope,
                        source_qualified_name=qualified_name,
                    )
                )

        elif node.type in ("import_statement", "import_from_statement"):
            rels = self._extract_import_relationships(
                node,
                source,
                file_id,
                source_line,
                source_column,
                symbol_name,
                scope,
                qualified_name,
            )
            relationships.extend(rels)

        elif node.type == "call":
            fn_node = node.child_by_field_name("function") or (
                node.children[0] if node.children else None
            )
            if fn_node is not None:
                fn_name = source[fn_node.start_byte : fn_node.end_byte].decode("utf-8").strip()
                if fn_name:
                    relationships.append(
                        RawRelationship(
                            source_file_id=file_id,
                            target_name=fn_name,
                            kind=RelationshipKind.CALLS,
                            source_line=source_line,
                            source_column=source_column,
                            source_symbol_name=symbol_name,
                            source_scope=scope,
                            source_qualified_name=qualified_name,
                        )
                    )

        elif node.type == "typed_parameter":
            type_node = node.child_by_field_name("type")
            if type_node is not None:
                type_str = source[type_node.start_byte : type_node.end_byte].decode("utf-8").strip()
                if type_str:
                    relationships.append(
                        RawRelationship(
                            source_file_id=file_id,
                            target_name=type_str,
                            kind=RelationshipKind.USES_TYPE,
                            source_line=source_line,
                            source_column=source_column,
                            source_symbol_name=symbol_name,
                            source_scope=scope,
                            source_qualified_name=qualified_name,
                        )
                    )

        return relationships

    def _extract_import_relationships(
        self,
        node: Node,
        source: bytes,
        file_id: UUID,
        source_line: int,
        source_column: int,
        symbol_name: str | None,
        scope: str | None,
        qualified_name: str | None,
    ) -> list[RawRelationship]:
        results: list[RawRelationship] = []
        if node.type == "import_statement":
            for child in node.children:
                if child.type in ("dotted_name", "aliased_import"):
                    name_node = (
                        child.child_by_field_name("name")
                        if child.type == "aliased_import"
                        else child
                    )
                    if name_node is not None:
                        imp_name = (
                            source[name_node.start_byte : name_node.end_byte]
                            .decode("utf-8")
                            .strip()
                        )
                        if imp_name:
                            results.append(
                                RawRelationship(
                                    source_file_id=file_id,
                                    target_name=imp_name,
                                    kind=RelationshipKind.IMPORTS,
                                    source_line=source_line,
                                    source_column=source_column,
                                    source_symbol_name=symbol_name,
                                    source_scope=scope,
                                    source_qualified_name=qualified_name,
                                    target_module_hint=imp_name,
                                )
                            )
        elif node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name") or self._find_first_child_of_type(
                node, "dotted_name"
            )
            module_hint = (
                source[module_node.start_byte : module_node.end_byte].decode("utf-8").strip()
                if module_node is not None
                else None
            )

            for child in node.children:
                if child.type in (
                    "import_prefix",
                    "from",
                    "import",
                    "dotted_name",
                    ",",
                    "(",
                    ")",
                    "whitespace",
                ):
                    if child == module_node:
                        continue
                    continue
                if child.type in ("aliased_import", "dotted_name", "identifier"):
                    name_node = (
                        child.child_by_field_name("name")
                        if child.type == "aliased_import"
                        else child
                    )
                    if name_node is not None:
                        imp_name = (
                            source[name_node.start_byte : name_node.end_byte]
                            .decode("utf-8")
                            .strip()
                        )
                        if imp_name and imp_name != module_hint:
                            results.append(
                                RawRelationship(
                                    source_file_id=file_id,
                                    target_name=imp_name,
                                    kind=RelationshipKind.IMPORTS,
                                    source_line=source_line,
                                    source_column=source_column,
                                    source_symbol_name=symbol_name,
                                    source_scope=scope,
                                    source_qualified_name=qualified_name,
                                    target_module_hint=module_hint,
                                )
                            )

        return results
