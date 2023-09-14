# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys
from pathlib import Path
from subprocess import check_output

import requests

import ophyd_async

# -- General configuration ------------------------------------------------
# Source code dir relative to this file
sys.path.insert(0, os.path.abspath("../../src"))

# General information about the project.
project = "ophyd-async"
copyright = "2014, Brookhaven National Lab"

# The full version, including alpha/beta/rc tags.
release = ophyd_async.__version__

# The short X.Y version.
if "+" in release:
    # Not on a tag, use branch name
    root = Path(__file__).absolute().parent.parent
    git_branch = check_output("git branch --show-current".split(), cwd=root)
    version = git_branch.decode().strip()
else:
    version = release

extensions = [
    # Use this for generating API docs
    "sphinx.ext.autodoc",
    "sphinx.ext.doctest",
    # This can parse google style docstrings
    "sphinx.ext.napoleon",
    # For linking to external sphinx documentation
    "sphinx.ext.intersphinx",
    # Add links to source code in API docs
    "sphinx.ext.viewcode",
    # Adds the inheritance-diagram generation directive
    "sphinx.ext.inheritance_diagram",
    # Add a copy button to each code block
    "sphinx_copybutton",
    # For the card element
    "sphinx_design",
    "sphinx.ext.autosummary",
    "sphinx.ext.mathjax",
    "sphinx.ext.githubpages",
    "IPython.sphinxext.ipython_directive",
    "IPython.sphinxext.ipython_console_highlighting",
    "matplotlib.sphinxext.plot_directive",
    "myst_parser",
    "numpydoc",
]

napoleon_google_docstring = False
napoleon_numpy_docstring = True

# If true, Sphinx will warn about all references where the target cannot
# be found.
# nitpicky = True

# A list of (type, target) tuples (by default empty) that should be ignored when
# generating warnings in "nitpicky mode". Note that type should include the
# domain name if present. Example entries would be ('py:func', 'int') or
# ('envvar', 'LD_LIBRARY_PATH').
nitpick_ignore = [
    ("py:class", "NoneType"),
    ("py:class", "'str'"),
    ("py:class", "'float'"),
    ("py:class", "'int'"),
    ("py:class", "'bool'"),
    ("py:class", "'object'"),
    ("py:class", "'id'"),
    ("py:class", "typing_extensions.Literal"),
]

# Both the class’ and the __init__ method’s docstring are concatenated and
# inserted into the main body of the autoclass directive
autoclass_content = "both"

# Order the members by the order they appear in the source code
autodoc_member_order = "bysource"

# Don't inherit docstrings from baseclasses
autodoc_inherit_docstrings = False

# Output graphviz directive produced images in a scalable format
graphviz_output_format = "svg"

# The name of a reST role (builtin or Sphinx extension) to use as the default
# role, that is, for text marked up `like this`
default_role = "any"

# The suffix of source filenames.
source_suffix = ".rst"

# The master toctree document.
master_doc = "index"

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# These patterns also affect html_static_path and html_extra_path
exclude_patterns = ["_build"]

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = "sphinx"


# Example configuration for intersphinx: refer to the Python standard library.
# This means you can link things like `str` and `asyncio` to the relevant
# docs in the python documentation.
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "bluesky": ("https://blueskyproject.io/bluesky/", None),
    "numpy": ("https://numpy.org/devdocs/", None),
    "databroker": ("https://blueskyproject.io/databroker/", None),
    "event-model": ("https://blueskyproject.io/event-model/main", None),
}

# A dictionary of graphviz graph attributes for inheritance diagrams.
inheritance_graph_attrs = dict(rankdir="TB")

# Common links that should be available on every page
rst_epilog = """
.. _NSLS: https://www.bnl.gov/nsls2
.. _black: https://github.com/psf/black
.. _flake8: https://flake8.pycqa.org/en/latest/
.. _isort: https://github.com/PyCQA/isort
.. _mypy: http://mypy-lang.org/
.. _pre-commit: https://pre-commit.com/
"""

# Ignore localhost links for periodic check that links in docs are valid
linkcheck_ignore = [r"http://localhost:\d+/"]

# Set copy-button to ignore python and bash prompts
# https://sphinx-copybutton.readthedocs.io/en/latest/use.html#using-regexp-prompt-identifiers
copybutton_prompt_text = r">>> |\.\.\. |\$ |In \[\d*\]: | {2,5}\.\.\.: | {5,8}: "
copybutton_prompt_is_regexp = True

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "pydata_sphinx_theme"
github_repo = project
github_user = "bluesky"
switcher_json = f"https://{github_user}.github.io/{github_repo}/switcher.json"
# Don't check switcher if it doesn't exist, but warn in a non-failing way
check_switcher = requests.get(switcher_json).ok
if not check_switcher:
    print(
        "*** Can't read version switcher, is GitHub pages enabled? \n"
        "    Once Docs CI job has successfully run once, set the "
        "Github pages source branch to be 'gh-pages' at:\n"
        f"    https://github.com/{github_user}/{github_repo}/settings/pages",
        file=sys.stderr,
    )

# Theme options for pydata_sphinx_theme
html_theme_options = dict(
    use_edit_page_button=True,
    github_url=f"https://github.com/{github_user}/{github_repo}",
    icon_links=[
        dict(
            name="PyPI",
            url=f"https://pypi.org/project/{project}",
            icon="fas fa-cube",
        ),
        dict(
            name="Gitter",
            url="https://gitter.im/NSLS-II/DAMA",
            icon="fas fa-person-circle-question",
        ),
    ],
    external_links=[
        dict(
            name="Bluesky Project",
            url="https://blueskyproject.io",
        )
    ],
)


# A dictionary of values to pass into the template engine’s context for all pages
html_context = dict(
    github_user=github_user,
    github_repo=project,
    github_version="master",
    doc_path="docs",
)

html_logo = "images/bluesky_ophyd_logo.svg"
html_favicon = "images/ophyd_favicon.svg"

# If true, "Created using Sphinx" is shown in the HTML footer. Default is True.
html_show_sphinx = False

# If true, "(C) Copyright ..." is shown in the HTML footer. Default is True.
html_show_copyright = False

# If False and a module has the __all__ attribute set, autosummary documents
# every member listed in __all__ and no others. Default is True
autosummary_ignore_module_all = False

# Turn on sphinx.ext.autosummary
autosummary_generate = True

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# Look for signatures in the first line of the docstring (used for C functions)
autodoc_docstring_signature = True

# numpydoc config
numpydoc_show_class_members = False

# Where to put Ipython savefigs
ipython_savefig_dir = "../build/savefig"
