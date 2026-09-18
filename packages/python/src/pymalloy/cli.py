import argparse
import json
import math
import sys
from pathlib import Path

from pymalloy.analysis import Diagnostic


def _parse_givens(text: str) -> dict:
    def invalid_number(value: str) -> None:
        raise ValueError(f"Given numbers must be finite: {value}")

    def number(value: str) -> float:
        result = float(value)
        if not math.isfinite(result):
            invalid_number(value)
        return result

    try:
        values = json.loads(text, parse_constant=invalid_number, parse_float=number)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"Invalid givens JSON: {error}") from error
    if not isinstance(values, dict):
        raise argparse.ArgumentTypeError("givens must be a JSON object")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check, format, and export Malloy analyses."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="export a runnable notebook")
    export.add_argument(
        "model", type=Path, help="local .malloy, .malloynb, or .malloysql file"
    )
    export.add_argument(
        "--format", choices=("marimo", "jupyter"), required=True, help="notebook format"
    )
    export.add_argument(
        "--profile",
        choices=("precompiled", "native", "widget"),
        default="precompiled",
        help="precompiled SQL, native model, or interactive browser widget (default: precompiled)",
    )
    export.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="output .py or .ipynb notebook (replaced on success)",
    )
    export.add_argument(
        "-q",
        "--query",
        action="append",
        default=[],
        help="named query, source.view, run:N, sql:N, or '*' for all (repeatable)",
    )
    export.add_argument(
        "--data-root",
        type=Path,
        help="directory for data paths (default: model directory)",
    )
    export.add_argument(
        "--database", type=Path, help="existing DuckDB database, opened read-only"
    )
    export.add_argument("--title", help="notebook title (default: model filename)")
    export.add_argument(
        "--givens",
        type=_parse_givens,
        metavar="JSON",
        help='given values as a JSON object, such as \'{"region": "North"}\'',
    )
    check = commands.add_parser(
        "check", help="check syntax, schemas, and model semantics"
    )
    check.add_argument("path", type=Path, help="local Malloy source file")
    check.add_argument(
        "--syntax-only",
        action="store_true",
        help="parse source without accessing data or imports",
    )
    check.add_argument(
        "--json", action="store_true", help="write a structured check report to stdout"
    )
    check.add_argument(
        "--data-root", type=Path, help="directory for relative data paths"
    )
    check.add_argument(
        "--database", type=Path, help="existing DuckDB database, opened read-only"
    )
    formatting = commands.add_parser(
        "format", help="format source with Malloy's experimental formatter"
    )
    formatting.add_argument("path", type=Path, help="local Malloy source file")
    formatting.add_argument(
        "--check",
        action="store_true",
        help="exit with status 1 if formatting would change the file",
    )
    args = parser.parse_args()
    if args.command != "export":
        _tool(args)
        return
    _export(args, export)


def _tool(args: argparse.Namespace) -> None:
    try:
        import duckdb

        from pymalloy.server import CompilationError, Session, SessionError
    except ImportError as error:
        print(
            f"pymalloy: {error}. Install language tools with pip install 'pymalloy[server]'",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    try:
        if args.command == "check":
            with Session(
                data_root=args.data_root,
                database=args.database,
                read_only=args.database is not None,
            ) as session:
                report = session.check_file(args.path, syntax_only=args.syntax_only)
            if args.json:
                print(json.dumps(report.to_dict(), ensure_ascii=False))
            else:
                for diagnostic in report.diagnostics:
                    _diagnostic(diagnostic, args.path)
                print(
                    f"{args.path}: {'OK' if report.ok else 'FAILED'}", file=sys.stderr
                )
            if not report.ok:
                raise SystemExit(1)
        else:
            with args.path.open(encoding="utf-8", newline="") as input_file:
                source = input_file.read()
            with Session() as session:
                formatted = session.format(source)
            if args.check:
                if source != formatted:
                    print(f"{args.path}: formatting required", file=sys.stderr)
                    raise SystemExit(1)
            else:
                sys.stdout.write(formatted)
    except CompilationError as error:
        if error.diagnostics:
            for diagnostic in error.diagnostics:
                _diagnostic(diagnostic, args.path)
        else:
            print(f"pymalloy: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, ValueError, TimeoutError, SessionError, duckdb.Error) as error:
        print(f"pymalloy: {error}", file=sys.stderr)
        raise SystemExit(1) from None


def _diagnostic(diagnostic: Diagnostic, path: Path) -> None:
    location = diagnostic.location
    at = (
        location.url
        if location and not location.url.startswith("memory:")
        else str(path)
    )
    if location:
        at += f":{location.range.start.line + 1}:{location.range.start.character + 1}"
    print(
        f"{at}: {diagnostic.severity} [{diagnostic.code}] {diagnostic.message}",
        file=sys.stderr,
    )


def _export(args: argparse.Namespace, export: argparse.ArgumentParser) -> None:
    suffix = ".py" if args.format == "marimo" else ".ipynb"
    if args.output.suffix != suffix:
        export.error(f"--output must end in {suffix} for --format {args.format}")
    if args.output.resolve() in {
        args.model.resolve(),
        args.database.resolve() if args.database else None,
    }:
        export.error("--output must differ from the model and database")
    try:
        from pymalloy.exports import compile_document, jupyter, marimo
        from pymalloy.server import CompilationError
    except ImportError as error:
        extra = "server,marimo" if args.format == "marimo" else "server"
        print(
            f"pymalloy: {error}. Install export dependencies with pip install 'pymalloy[{extra}]'",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    try:
        document = compile_document(
            args.model,
            profile=args.profile,
            queries=args.query,
            givens=args.givens,
            data_root=args.data_root,
            database=args.database,
            title=args.title,
        )
        renderer = marimo if args.format == "marimo" else jupyter
        source = renderer.render(document, output_path=args.output)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(source, encoding="utf-8")
    except (CompilationError, ImportError, OSError) as error:
        print(f"pymalloy: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"Wrote {args.output} ({len(document.queries)} queries)", file=sys.stderr)
