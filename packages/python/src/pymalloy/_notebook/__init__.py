"""Notebook representation hooks shared by immutable values and runtime handles."""


class NotebookDisplay:
    def _notebook_subject(self):
        from .subject import describe

        return describe(self)

    def _display_(self):
        from pymalloy.widget import MalloyWidget

        from .lifetime import own_display

        widget = MalloyWidget(self, auto_run=False, _transient=True)
        try:
            own_display(widget)
        except BaseException:
            widget.close()
            raise
        return widget

    def _repr_mimebundle_(self, include=None, exclude=None):
        mime = "application/vnd.jupyter.widget-view+json"
        plain = {"text/plain": getattr(self, "text", type(self).__name__)}
        if (include is not None and mime not in include) or (
            exclude is not None and mime in exclude
        ):
            return {
                key: value
                for key, value in plain.items()
                if (include is None or key in include)
                and (exclude is None or key not in exclude)
            }
        widget = self._display_()
        rendered = widget._repr_mimebundle_()
        assert rendered is not None
        data, metadata = rendered
        bundle = {
            key: value
            for key, value in {**data, **plain}.items()
            if (include is None or key in include)
            and (exclude is None or key not in exclude)
        }
        return bundle, {key: value for key, value in metadata.items() if key in bundle}
