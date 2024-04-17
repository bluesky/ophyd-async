2. Adopt python_copier_template for project structure
=====================================================

Date: 2022-02-18

Status
------

Accepted

Context
-------

We should use the following `python_copier_template <https://github.com/DiamondLightSource/python_copier_template>`_.
The template will ensure consistency in developer
environments and package management.

Decision
--------

We have switched to using the skeleton.

Consequences
------------

This module will use a fixed set of tools as developed in python_copier_template
and can pull from this template to update the packaging to the latest techniques.

As such, the developer environment may have changed, the following could be
different:

- linting
- formatting
- pip venv setup
- CI/CD
