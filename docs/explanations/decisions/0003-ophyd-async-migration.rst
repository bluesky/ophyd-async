3. Ophyd Async migration
========================

Date: 2023-08-22

Status
------

Accepted

Context
-------

For over a year, developers of the Bluesky collaboration have been aware of, and 
contributing to, the development of Ophyd v2. This was envisioned as the successor
and eventual replacement to Ophyd, Bluesky's hardware abstraction library. 

Over time, contributions to Ophyd v2 have grown, and Bluesky collaborators would
like to maintain support for Ophyd v1 even after Ophyd v2 has been released. Were
Ophyd v1 and v2 to live in the same repository, this would present some key issues:

1. Tagged releases would become complicated. When Ophyd v2 is provisionally released,
this will be done on a 'v2.x.x' tag, however development on Ophyd v1 will still
continue. This means any releases targeting Ophyd v1 would need to revert to a 'v1.x.x'
tag, which shows a confusing commit and tagging history.
2. Tests for Ophyd v1 and v2 would both be run for CI/CD jobs. This increases the
time it takes for PR's to be approved for both instances.

Ophyd v1 and Ophyd v2 are, in theory, two separate codebases. They originate from a
similar place; but there is no reason for them to be stored in the same repository.

Decision
--------

Considering the complications of tracking two major versions in git history, and the
additional time sink of Ophyd v1 testing in v2 development, we have decided to 
separate Ophyd v2 into its own repository, Ophyd Async.

There are currently two repositories in the Bluesky organization on Github which use
Ophyd Async to define devies for two underlying control systems, EPICS and Tango. These
repositories (ophyd-epics-devices and ophyd-tango-devices respectively) will be merged
into Ophyd Async as well.

Relevant history between all three repositories should be preserved.

Consequences
------------

This will require changing the repository structure of Ophyd Async; see 
the decision on repository structure :doc:`0004-repository-structure` for details.