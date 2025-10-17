This system test runs against the eiger tickit sim. To run it:

0. Ensure you have disabled SELinux (https://dev-portal.diamond.ac.uk/guide/containers/tutorials/podman/#enable-use-of-vscode-features)
1. Run `podman run --rm -it -v /dev/shm:/dev/shm -v /tmp:/tmp --net=host ghcr.io/diamondlightsource/eiger-detector-runtime:1.16.0beta5` this will bring up the simulator itself.
2. In a separate terminal load a python environment with `ophyd-async` in it
3. `cd system_tests/epics/eiger` and `./start_iocs_and_run_tests.sh`
