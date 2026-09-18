import duckdb
import pytest

import pymalloy as pm


@pytest.mark.parametrize("preview", [False, True])
def test_engine_failure_retains_replay_context_and_original_exception(
    tmp_path, preview
):
    dependency = tmp_path / "values.malloy"
    dependency.write_text("source: values is duckdb.sql(\"SELECT 'invalid' AS value\")")
    source = tmp_path / "model.malloy"
    source.write_text("""##! experimental.givens
given: cutoff :: number is 0
import "values.malloy"
query: failure is values -> { select: converted is value::number, cutoff is $cutoff }
""")
    model = pm.model(source)
    parameters = {"cutoff": 9007199254740993}
    try:
        query = model.query("failure")
        with pytest.raises(pm.ExecutionError) as failed:
            query.preview(givens=parameters) if preview else query.run(
                givens=parameters
            )
        context = failed.value.context
        assert isinstance(failed.value.__cause__, duckdb.ConversionException)
        assert context.query.name == "failure"
        assert context.compiler_version == pm.check(source).compiler_version
        assert context.sql == query.sql(givens=parameters)
        assert context.preview_limit == (20 if preview else None)
    finally:
        model.close()
    parameters["cutoff"] = 0
    assert context.givens == {"cutoff": 9007199254740993}
    source.unlink()
    dependency.unlink()
    replay = pm.model(context.source)
    try:
        with pytest.raises(pm.ExecutionError) as repeated:
            replay.query(context.query.name).run(givens=context.givens)
        assert repeated.value.context.sql == context.sql
    finally:
        replay.close()


def test_assertion_engine_failure_keeps_execution_evidence():
    candidate = pm.draft().define(values=pm.sql("SELECT 'invalid' AS value"))
    report = candidate.validate(
        {
            "numeric": pm.ref("values").pipe(
                pm.query(pm.select(value=pm.col("value").cast("number")))
            )
        }
    )
    assert not report.ok
    check = report.checks[0]
    assert check.status == "error"
    assert check.execution is not None
    assert (
        check.execution.malloy
        == "run: "
        + pm.ref("values")
        .pipe(pm.query(pm.select(value=pm.col("value").cast("number"))))
        .text
    )


def test_schema_failure_keeps_native_diagnostics_sql_and_engine_cause():
    with pytest.raises(pm.CompilationError) as failed:
        pm.model("run: duckdb.sql('SELECT absent_column') -> { select: * }")
    schema = failed.value.__cause__
    assert isinstance(schema, pm.SchemaError)
    assert schema.sql == "DESCRIBE SELECT absent_column"
    assert isinstance(schema.__cause__, duckdb.BinderException)
    assert failed.value.diagnostics


def test_ad_hoc_failure_captures_new_imports_for_detached_replay(tmp_path):
    imported = tmp_path / "values.malloy"
    imported.write_text("source: values is duckdb.sql(\"SELECT 'invalid' AS value\")")
    model = pm.model(
        "source: base is duckdb.sql('SELECT 1 AS id')",
        url=(tmp_path / "root.malloy").as_uri(),
    )
    try:
        with pytest.raises(pm.ExecutionError) as failed:
            model.query(
                malloy='import "values.malloy"\nrun: values -> {select: value is value::number}'
            ).run()
        context = failed.value.context
        assert imported.as_uri() in context.source.imports
    finally:
        model.close()
    imported.unlink()
    replay = pm.model(context.source)
    try:
        with pytest.raises(pm.ExecutionError) as repeated:
            replay.query(malloy=context.malloy).run(givens=context.givens)
        assert repeated.value.context.sql == context.sql
    finally:
        replay.close()
