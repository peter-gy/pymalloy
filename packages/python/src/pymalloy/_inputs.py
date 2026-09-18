"""Immutable Arrow input values and their independently owned materializations."""

from __future__ import annotations

import base64
import hashlib
import io
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MaterializedInput:
    path: Path
    sha256: str
    schema: str
    arrow_schema: str
    rows: int


class _Storage:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.directory: tempfile.TemporaryDirectory[str] | None = None
        self.artifact: MaterializedInput | None = None


@dataclass(frozen=True, eq=False)
class DataInput:
    """Captured input data. Values and schemas are independent of the original producer."""

    name: str
    id: str
    rows: int
    _ipc: bytes = field(repr=False)
    _storage: _Storage = field(default_factory=_Storage, repr=False, compare=False)

    @property
    def reference(self) -> str:
        return f"pymalloy-inputs/{self.id}.parquet"

    @cached_property
    def fingerprint(self) -> str:
        return hashlib.sha256(self._ipc).hexdigest()

    def arrow(self) -> Any:
        import pyarrow as pa

        return pa.ipc.open_stream(pa.py_buffer(self._ipc)).read_all()

    def materialize(self) -> MaterializedInput:
        """Write once, retain the file for this value's lifetime, and reuse exact bytes."""
        import pyarrow.parquet as pq

        with self._storage.lock:
            if self._storage.artifact is None:
                directory = tempfile.TemporaryDirectory(prefix="pymalloy-input-")
                path = Path(directory.name) / "data.parquet"
                try:
                    table = self.arrow()
                    pq.write_table(
                        table,
                        path,
                        compression="zstd",
                        version="2.6",
                        use_compliant_nested_type=False,
                    )
                    with pq.ParquetFile(path) as parquet:
                        offset = 0
                        if not table.schema.equals(
                            parquet.schema_arrow, check_metadata=True
                        ):
                            raise ValueError(
                                "Parquet materialization changed an input's schema"
                            )
                        for batch in parquet.iter_batches(batch_size=65536):
                            if not _same_table(
                                table.slice(offset, batch.num_rows), batch
                            ):
                                raise ValueError(
                                    "Parquet materialization changed an input's values"
                                )
                            offset += batch.num_rows
                        if offset != self.rows:
                            raise ValueError(
                                "Parquet materialization changed an input's row count"
                            )
                    with path.open("rb") as stream:
                        digest = hashlib.file_digest(stream, "sha256").hexdigest()
                    artifact = MaterializedInput(
                        path,
                        digest,
                        str(table.schema),
                        base64.b64encode(table.schema.serialize()).decode("ascii"),
                        self.rows,
                    )
                except BaseException:
                    directory.cleanup()
                    raise
                self._storage.directory = directory
                self._storage.artifact = artifact
            return self._storage.artifact


def snapshot_data(value: Any, *, name: str | None = None) -> DataInput:
    try:
        import pyarrow as pa
    except ModuleNotFoundError as error:
        raise ImportError(
            "Dataframe inputs require pyarrow or pymalloy[dataframes]"
        ) from error
    if type(value).__name__ == "LazyFrame" and type(value).__module__.startswith(
        "polars"
    ):
        raise TypeError(
            "Collect the Polars LazyFrame explicitly before pm.data(): pm.data(frame.collect())"
        )
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise ValueError("Input names must be nonempty strings")
    if isinstance(value, pa.RecordBatchReader):
        raise TypeError(
            "Read the Arrow stream explicitly before pm.data(): pm.data(reader.read_all())"
        )
    try:
        if type(value).__module__.startswith("pandas."):
            table = pa.Table.from_pandas(value, preserve_index=False)
        else:
            table = pa.table(value)
    except (TypeError, ValueError, pa.ArrowException) as error:
        raise TypeError(
            "pm.data requires materialized dataframe-like data convertible through Arrow"
        ) from error
    if len(set(table.column_names)) != table.num_columns or any(
        not key for key in table.column_names
    ):
        raise ValueError("Input columns require unique, nonempty names")
    target = pa.schema(
        [column.with_type(_portable_type(column.type)) for column in table.schema],
        metadata=table.schema.metadata,
    )
    try:
        table = table.cast(target, safe=True)
    except pa.ArrowException as error:
        raise TypeError(
            "Input conversion would lose temporal precision; cast explicitly before pm.data()"
        ) from error
    _validate_schema(table.schema)
    sink = io.BytesIO()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    identity = uuid.uuid4().hex
    return DataInput(
        name or f"input_{identity}",
        identity,
        table.num_rows,
        sink.getvalue(),
    )


def _validate_schema(schema: Any, prefix: str = "") -> None:
    import pyarrow as pa

    if len({column.name for column in schema}) != len(schema) or any(
        not column.name for column in schema
    ):
        raise ValueError(f"{prefix or 'Input'} requires unique, nonempty field names")
    for column in schema:
        path = prefix + column.name
        dtype = column.type
        if pa.types.is_struct(dtype):
            _validate_schema(dtype, path + ".")
        elif (
            pa.types.is_list(dtype)
            or pa.types.is_large_list(dtype)
            or pa.types.is_fixed_size_list(dtype)
        ):
            _validate_schema(pa.schema([dtype.value_field]), path + ".")
        elif pa.types.is_dictionary(dtype):
            _validate_schema(
                pa.schema([pa.field(column.name, dtype.value_type)]), prefix
            )
        elif pa.types.is_decimal(dtype):
            if dtype.precision > 38:
                raise TypeError(
                    f"{path}: decimal precision above 38 is not portable to DuckDB/Malloy"
                )
        elif pa.types.is_timestamp(dtype):
            if dtype.unit == "ns":
                raise TypeError(
                    f"{path}: nanosecond timestamps require an explicit cast to microseconds for the Python runtime"
                )
        elif not (
            pa.types.is_null(dtype)
            or pa.types.is_boolean(dtype)
            or pa.types.is_integer(dtype)
            or pa.types.is_floating(dtype)
            or pa.types.is_string(dtype)
            or pa.types.is_large_string(dtype)
            or pa.types.is_string_view(dtype)
            or pa.types.is_date(dtype)
        ):
            raise TypeError(
                f"{path}: Arrow type {dtype} needs an explicit portable conversion before pm.data()"
            )


def _portable_type(dtype: Any) -> Any:
    import pyarrow as pa

    if pa.types.is_timestamp(dtype) and dtype.unit == "ns":
        return pa.timestamp("us", tz=dtype.tz)
    if pa.types.is_struct(dtype):
        return pa.struct(
            [column.with_type(_portable_type(column.type)) for column in dtype]
        )
    if pa.types.is_list(dtype):
        return pa.list_(dtype.value_field.with_type(_portable_type(dtype.value_type)))
    if pa.types.is_large_list(dtype):
        return pa.large_list(
            dtype.value_field.with_type(_portable_type(dtype.value_type))
        )
    if pa.types.is_fixed_size_list(dtype):
        return pa.list_(
            dtype.value_field.with_type(_portable_type(dtype.value_type)),
            dtype.list_size,
        )
    return dtype


def _same_table(left: Any, right: Any) -> bool:
    if (
        not left.schema.equals(right.schema, check_metadata=True)
        or left.num_rows != right.num_rows
    ):
        return False
    return all(
        _same_array(a.chunk(0) if a.num_chunks == 1 else a.combine_chunks(), b)
        for a, b in zip(left.columns, right.columns, strict=True)
    )


def _same_array(left: Any, right: Any) -> bool:
    import pyarrow as pa
    import pyarrow.compute as pc

    dtype = left.type
    if pa.types.is_floating(dtype):
        bits = {16: pa.uint16(), 32: pa.uint32(), 64: pa.uint64()}[dtype.bit_width]
        return left.view(bits).equals(right.view(bits))
    if pa.types.is_struct(dtype):
        if (left.null_count or right.null_count) and not left.is_null().equals(
            right.is_null()
        ):
            return False
        return all(
            _same_array(a, b)
            for a, b in zip(left.flatten(), right.flatten(), strict=True)
        )
    if (
        pa.types.is_list(dtype)
        or pa.types.is_large_list(dtype)
        or pa.types.is_fixed_size_list(dtype)
    ):
        return pc.call_function("list_value_length", [left]).equals(
            pc.call_function("list_value_length", [right])
        ) and _same_array(left.flatten(), right.flatten())
    if pa.types.is_dictionary(dtype):
        return _same_array(left.dictionary_decode(), right.dictionary_decode())
    return left.equals(right)
