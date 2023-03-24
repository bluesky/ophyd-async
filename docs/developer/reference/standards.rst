Standards
=========

This document defines the code and documentation standards used in this
repository.

Code Standards
--------------

The code in this repository conforms to standards set by the following tools:

- black_ for code formatting
- flake8_ for style checks
- isort_ for import ordering
- mypy_ for static type checking

.. seealso::

    How-to guides `../how-to/lint` and `../how-to/static-analysis`

.. _documentation_standards:

Documentation Standards
-----------------------

Docstrings are pre-processed using the Sphinx Napoleon extension. As such,
numpydoc-style_ is considered as standard for this repository. Please use type
hints in the function signature for types. For example:

.. code:: python

    def foo(var1, var2, *args, long_var_name="hi", only_seldom_used_keyword=0, **kwargs):
    r"""Summarize the function in one line.

    Several sentences providing an extended description. Refer to
    variables using back-ticks, e.g. `var`.

    Parameters
    ----------
    var1 : array_like
        Array_like means all those objects -- lists, nested lists, etc. --
        that can be converted to an array.  We can also refer to
        variables like `var1`.
    var2 : int
        The type above can either refer to an actual Python type
        (e.g. ``int``), or describe the type of the variable in more
        detail, e.g. ``(N,) ndarray`` or ``array_like``.
    *args : iterable
        Other arguments.
    long_var_name : {'hi', 'ho'}, optional
        Choices in brackets, default first when optional.

    Returns
    -------
    type
        Explanation of anonymous return value of type ``type``.
    describe : type
        Explanation of return value named `describe`.
    out : type
        Explanation of `out`.
    type_without_description

    Other Parameters
    ----------------
    only_seldom_used_keyword : int, optional
        Infrequently used parameters can be described under this optional
        section to prevent cluttering the Parameters section.
    **kwargs : dict
        Other infrequently used keyword arguments. Note that all keyword
        arguments appearing after the first parameter specified under the
        Other Parameters section, should also be described under this
        section.

    Raises
    ------
    BadException
        Because you shouldn't have done that.

    See Also
    --------
    numpy.array : Relationship (optional).
    numpy.ndarray : Relationship (optional), which could be fairly long, in
                    which case the line wraps here.
    numpy.dot, numpy.linalg.norm, numpy.eye

    Notes
    -----
    Notes about the implementation algorithm (if needed).

    This can have multiple paragraphs.

    You may include some math:

    .. math:: X(e^{j\omega } ) = x(n)e^{ - j\omega n}

    And even use a Greek symbol like :math:`\omega` inline.

    References
    ----------
    Cite the relevant literature, e.g. [1]_.  You may also cite these
    references in the notes section above.

    .. [1] O. McNoleg, "The integration of GIS, remote sensing,
       expert systems and adaptive co-kriging for environmental habitat
       modelling of the Highland Haggis using object-oriented, fuzzy-logic
       and neural-network techniques," Computers & Geosciences, vol. 22,
       pp. 585-588, 1996.

    Examples
    --------
    These are written in doctest format, and should illustrate how to
    use the function.

    >>> a = [1, 2, 3]
    >>> print([x + 3 for x in a])
    [4, 5, 6]
    >>> print("a\nb")
    a
    b

    """
    pass

.. _numpydoc-style: https://numpydoc.readthedocs.io/en/latest/format.html

Documentation is contained in the ``docs`` directory and extracted from
docstrings of the API.

Docs follow the underlining convention::

    Headling 1 (page title)
    =======================

    Heading 2
    ---------

    Heading 3
    ~~~~~~~~~

.. seealso::

    How-to guide `../how-to/build-docs`