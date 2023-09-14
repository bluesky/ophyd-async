5. Respect black line length
============================

Date: 2023-08-30

Status
------

Accepted

Context
-------

We should adhere to black's default settings and line length.

From black's own documentation:
> "You probably noticed the peculiar default line length. Black defaults to 88 characters per line, which happens to be 10% over 80. This number was found to produce significantly shorter files than sticking with 80 (the most popular), or even 79 (used by the standard library). In general, 90-ish seems like the wise choice.
... remember that people with sight disabilities find it harder to work with line lengths exceeding 100 characters. It also adversely affects side-by-side diff review on typical screen resolutions. Long lines also make it harder to present code neatly in documentation or talk slides."

Decision
--------

We have configured linting tools to use black's default line length of 88.

Consequences
------------

Linting tools for this repository are configured to accept black's line length of 88 characters.
Any additional linting tools should respect this.