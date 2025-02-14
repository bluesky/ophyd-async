import re

from autodoc2.render.myst_ import MystRenderer

DOTTED_MODULE = re.compile(r"((?:[a-zA-Z_][a-zA-Z_0-9]+\.)+)")


class ShortenedNamesRenderer(MystRenderer):
    def format_annotation(self, annotation):
        if annotation:
            annotation = DOTTED_MODULE.sub(r"~\1", annotation)
        return super().format_annotation(annotation)
