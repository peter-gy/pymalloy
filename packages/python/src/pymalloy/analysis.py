"""Typed language reports generated from the compiler contract."""

from pymalloy._records import (
    AnnotationInfo,
    CheckReport,
    Diagnostic,
    DocumentCell,
    GivenInfo,
    ImportInfo,
    Inspection,
    MarkdownCell,
    NativeMetadata,
    ParseReport,
    QueryCell,
    QueryDescriptor,
    SourceLocation,
    SourcePosition,
    SourceRange,
    SymbolInfo,
)
from pymalloy._wire import to_dict

__all__ = [
    "AnnotationInfo",
    "CheckReport",
    "Diagnostic",
    "DocumentCell",
    "GivenInfo",
    "ImportInfo",
    "Inspection",
    "MarkdownCell",
    "NativeMetadata",
    "ParseReport",
    "QueryCell",
    "QueryDescriptor",
    "SourceLocation",
    "SourcePosition",
    "SourceRange",
    "SymbolInfo",
    "to_dict",
]
