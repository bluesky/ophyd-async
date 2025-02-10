import re

from autodoc2.render.myst_ import MystRenderer
from docutils import nodes
from myst_parser.parsers.sphinx_ import MystParser
from sphinx.ext.napoleon import docstring

DOTTED_MODULE = re.compile(r"((?:[a-zA-Z_][a-zA-Z_0-9]+\.)+)")


class ShortenedNamesRenderer(MystRenderer):
    def format_annotation(self, annotation):
        if annotation:
            annotation = DOTTED_MODULE.sub(r"~\1", annotation)
        return super().format_annotation(annotation)


class NapoleonParser(MystParser):
    def parse(self, inputstring: str, document: nodes.document) -> None:
        parsed_content = "```{eval-rst}\n"
        parsed_content += str(
            docstring.GoogleDocstring(str(docstring.NumpyDocstring(inputstring)))
        )
        parsed_content += "\n```\n"
        return super().parse(parsed_content, document)


Parser = NapoleonParser
