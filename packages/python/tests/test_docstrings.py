"""Execute public API examples in their defining modules."""

import doctest
import importlib
import inspect
from functools import cached_property

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "pymalloy",
        "pymalloy.authoring",
        "pymalloy.expressions",
        "pymalloy._authoring.draft",
        "pymalloy._authoring.syntax",
        "pymalloy._model.source",
        "pymalloy._model.inputs",
        "pymalloy._server.api",
        "pymalloy._server.runtime",
        "pymalloy._server.tooling",
        "pymalloy.result",
        "pymalloy.validation",
        "pymalloy.widget",
        "pymalloy.browser",
    ],
)
def test_public_api_examples(module_name):
    module = importlib.import_module(module_name)
    finder = doctest.DocTestFinder()
    examples = finder.find(module)
    # Standard doctest discovery handles property but not cached_property.
    for cls in vars(module).values():
        if not inspect.isclass(cls) or cls.__module__ != module_name:
            continue
        for name, attribute in vars(cls).items():
            if isinstance(attribute, cached_property):
                examples.extend(
                    finder.find(
                        attribute.func, name=f"{module_name}.{cls.__name__}.{name}"
                    )
                )
    runner = doctest.DocTestRunner(
        optionflags=doctest.ELLIPSIS | doctest.DONT_ACCEPT_TRUE_FOR_1,
    )
    for example in examples:
        runner.run(example)
    result = runner.summarize()
    assert result.failed == 0, f"{module_name}: {result.failed} doctest failures"
