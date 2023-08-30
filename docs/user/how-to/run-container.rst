Run in a container
==================

Pre-built containers with ophyd_async and its dependencies already
installed are available on `Github Container Registry
<https://ghcr.io/bluesky/ophyd_async>`_.

Starting the container
----------------------

To pull the container from github container registry and run::

    $ docker run ghcr.io/bluesky/ophyd_async:main --version

To get a released version, use a numbered release instead of ``main``.
