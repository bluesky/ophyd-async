"""Configuration file for the Sphinx documentation builder.

This file only contains a selection of the most common options. For a full
list see the documentation:
https://www.sphinx-doc.org/en/master/usage/configuration.html
"""

import sys
from pathlib import Path
from subprocess import check_output

import requests
from sphinx import addnodes, application, environment
from sphinx.ext import intersphinx

import ophyd_async


def missing_reference_handler(
    app: application.Sphinx,
    env: environment.BuildEnvironment,
    node: addnodes.pending_xref,
    contnode,
):
    """Find refs for TypeVars and Unions."""
    target = node["reftarget"]
    if "." in target and node["reftype"] == "class":
        # Try again as `obj` so we pick up Unions, TypeVars and other things
        if target.startswith("ophyd_async"):
            # Pick it up from our domain
            domain = env.domains[node["refdomain"]]
            refdoc = node.get("refdoc")
            return domain.resolve_xref(
                env, refdoc, app.builder, "obj", target, node, contnode
            )
        else:
            # pass it to intersphinx with the right type
            node["reftype"] = "obj"
            return intersphinx.missing_reference(app, env, node, contnode)


def setup(app: application.Sphinx):
    """Add the custom handler to the Sphinx app."""
    app.connect("missing-reference", missing_reference_handler)


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
    # for diagrams
    "sphinxcontrib.mermaid",
    # Use this for generating API docs
    "autodoc2",
    # For linking to external sphinx documentation
    "sphinx.ext.intersphinx",
    # Add links to source code in API docs
    "sphinx.ext.viewcode",
    # Add a copy button to each code block
    "sphinx_copybutton",
    # For the card element
    "sphinx_design",
    # To make .nojekyll
    "sphinx.ext.githubpages",
    # To make the {ipython} directive
    "IPython.sphinxext.ipython_directive",
    # To syntax highlight "ipython" language code blocks
    "IPython.sphinxext.ipython_console_highlighting",
    # To embed matplotlib plots generated from code
    "matplotlib.sphinxext.plot_directive",
    # To parse markdown
    "myst_parser",
]

# Which package to load and document
autodoc2_packages = [{"path": "../src/ophyd_async", "auto_mode": True}]

# Put them in docs/_api which is git ignored
autodoc2_output_dir = "_api"

# Modules that should have an all...
autodoc2_module_all_regexes = [
    r"ophyd_async\.core",
    r"ophyd_async\.sim",
    r"ophyd_async\.epics\.[^\.]*",
    r"ophyd_async\.tango\.[^\.]*",
    r"ophyd_async\.fastcs\.[^\.]*",
    r"ophyd_async\.plan_stubs",
    r"ophyd_async\.testing",
]

# ... so should have their private modules ignored
autodoc2_skip_module_regexes = [
    x + r"\._.*" for x in autodoc2_module_all_regexes + ["ophyd_async"]
]

# Render with shortened names
autodoc2_render_plugin = "ophyd_async._docs_parser.ShortenedNamesRenderer"

# Don't document private things
autodoc2_hidden_objects = {"private", "dunder", "inherited"}

# We don't have any docstring for __init__, so by separating
# them here we don't get the "Initilize" text that would otherwise be added
autodoc2_class_docstring = "both"

# For some reason annotations are not expanded, this will do here
autodoc2_replace_annotations = [
    ("~PvSuffix.rbv", "ophyd_async.epics.core.PvSuffix.rbv"),
    ("typing_extensions.Self", "typing.Self"),
]

# Which objects to include docstrings for. ‘direct’ means only from objects
# that are not inherited.
autodoc2_docstrings = "all"

# So we can use the ::: syntax and the :param thing: syntax
myst_enable_extensions = ["colon_fence", "fieldlist"]

# If true, Sphinx will warn about all references where the target cannot
# be found.
nitpicky = True

# A list of (type, target) tuples (by default empty) that should be ignored when
# generating warnings in "nitpicky mode". Note that type should include the
# domain name if present. Example entries would be ('py:func', 'int') or
# ('envvar', 'LD_LIBRARY_PATH').
obj_ignore = [
    "ophyd_async.core._derived_signal_backend.RawT",
    "ophyd_async.core._derived_signal_backend.DerivedT",
    "ophyd_async.core._detector.DetectorControllerT",
    "ophyd_async.core._detector.DetectorWriterT",
    "ophyd_async.core._device.DeviceT",
    "ophyd_async.core._device_filler.SignalBackendT",
    "ophyd_async.core._device_filler.DeviceConnectorT",
    "ophyd_async.core._derived_signal_backend.TransformT",
    "ophyd_async.core._protocol.C",
    "ophyd_async.core._signal_backend.SignalDatatypeV",
    "ophyd_async.core._status.AsyncStatusBase",
    "ophyd_async.core._utils.P",
    "ophyd_async.core._utils.T",
    "ophyd_async.core._utils.V",
    "ophyd_async.epics.adcore._core_logic.ADBaseIOT",
    "ophyd_async.epics.adcore._core_logic.ADBaseControllerT",
    "ophyd_async.epics.adcore._core_writer.NDFileIOT",
    "ophyd_async.epics.adcore._core_writer.ADWriterT",
    "ophyd_async.tango.core._base_device.T",
    "ophyd_async.tango.core._tango_transport.P",
    "ophyd_async.tango.core._tango_transport.R",
    "ophyd_async.tango.core._tango_transport.TangoProxy",
    "ophyd_async.testing._utils.T",
    "ophyd_async.sim._mirror.TwoJackRaw",
    "ophyd_async.sim._mirror.TwoJackDerived",
    "0.1",
    "1.0",
]
nitpick_ignore = []
for var in obj_ignore:
    nitpick_ignore.append(("py:class", var))
    nitpick_ignore.append(("py:obj", var))
# Ignore classes in modules with no intersphinx
nitpick_ignore_regex = [
    (r"py:.*", r"pydantic\..*"),
    (r"py:.*", r"tango\..*"),
]

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
    "bluesky": ("https://blueskyproject.io/bluesky/main", None),
    "scanspec": ("https://blueskyproject.io/scanspec/main", None),
    "numpy": ("https://numpy.org/devdocs/", None),
    "databroker": ("https://blueskyproject.io/databroker/", None),
    "event-model": ("https://blueskyproject.io/event-model/main", None),
    "pytest": ("https://docs.pytest.org/en/stable/", None),
}

# A dictionary of graphviz graph attributes for inheritance diagrams.
inheritance_graph_attrs = {"rankdir": "TB"}

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
github_repo = "ophyd-async"
github_user = "bluesky"
switcher_json = "https://blueskyproject.io/ophyd-async/switcher.json"
switcher_exists = requests.get(switcher_json).ok
if not switcher_exists:
    print(
        "*** Can't read version switcher, is GitHub pages enabled? \n"
        "    Once Docs CI job has successfully run once, set the "
        "Github pages source branch to be 'gh-pages' at:\n"
        f"    https://github.com/{github_user}/{github_repo}/settings/pages",
        file=sys.stderr,
    )

# Theme options for pydata_sphinx_theme
# We don't check switcher because there are 3 possible states for a repo:
# 1. New project, docs are not published so there is no switcher
# 2. Existing project with latest skeleton, switcher exists and works
# 3. Existing project with old skeleton that makes broken switcher,
#    switcher exists but is broken
# Point 3 makes checking switcher difficult, because the updated skeleton
# will fix the switcher at the end of the docs workflow, but never gets a chance
# to complete as the docs build warns and fails.
html_theme_options = {
    "use_edit_page_button": True,
    "github_url": f"https://github.com/{github_user}/{github_repo}",
    "icon_links": [
        {
            "name": "PyPI",
            "url": f"https://pypi.org/project/{project}",
            "icon": "fas fa-cube",
        },
    ],
    "switcher": {
        "json_url": switcher_json,
        "version_match": version,
    },
    "check_switcher": False,
    "navbar_end": ["theme-switcher", "icon-links", "version-switcher"],
    "external_links": [
        {
            "name": "Bluesky Project",
            "url": "https://blueskyproject.io",
        },
    ],
    "navigation_with_keys": False,
    "show_toc_level": 3,
}

# A dictionary of values to pass into the template engine’s context for all pages
html_context = {
    "github_user": github_user,
    "github_repo": project,
    "github_version": version,
    "doc_path": "docs",
}

# If true, "Created using Sphinx" is shown in the HTML footer. Default is True.
html_show_sphinx = False

# If true, "(C) Copyright ..." is shown in the HTML footer. Default is True.
html_show_copyright = False

# Logo
html_logo = "images/ophyd-async-logo.svg"
html_favicon = "images/ophyd-favicon.svg"

# Custom CSS
html_static_path = ["_static"]
html_css_files = ["custom.css"]

# Where to put Ipython savefigs
ipython_savefig_dir = "../build/savefig"
