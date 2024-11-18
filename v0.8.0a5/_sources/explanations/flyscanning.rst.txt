Flyscanning
===========

See the documents in the [bluesky cookbook](http://blueskyproject.io/bluesky-cookbook/glossary/flyscanning.html)

Hardware
--------

Ophyd-async ships with support for Quantum Detectors' PandA_ and Zebra_ as triggering mechanisms.

These are very modular and can be used to trigger a variety of detectors and handle readback signals from a variety of sample control devices. See full specs for more information.

It is possible to write support for additional systems/devices.


Role of Ophyd-Async
-------------------

Bluesky supports devices that configure acquisition and then hand over control to an external system via the ``Flyer`` protocol. 

Ophyd-async's job is to provide devices that implement ``Flyer`` and can:

- Configure all necessary hardware for a scan
- Kickoff a scan and monitor progress until complete
- Produce documents representing the progress of the scan
- Allow handing control back and forth to enable outer scanning

.. _PandA: https://quantumdetectors.com/products/pandabox/
.. _Zebra: https://quantumdetectors.com/products/zebra/
