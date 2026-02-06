"""Helper script to test transport unavailability by blocking module imports."""

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Test EPICS signal creation with blocked transports"
    )
    parser.add_argument(
        "--block-ca",
        action="store_true",
        help="Block aioca import to simulate CA unavailable",
    )
    parser.add_argument(
        "--block-pva",
        action="store_true",
        help="Block p4p import to simulate PVA unavailable",
    )
    parser.add_argument("pv_name", type=str, help="PV name to use for signal creation")

    args = parser.parse_args()

    # Block the requested transports
    if args.block_ca:
        sys.modules["aioca"] = None  # type: ignore

    if args.block_pva:
        sys.modules["p4p"] = None  # type: ignore
        sys.modules["p4p.client"] = None  # type: ignore
        sys.modules["p4p.client.thread"] = None  # type: ignore

    # Now try to import and use ophyd_async
    from ophyd_async.epics.core import epics_signal_rw

    # Try to create a signal - let exceptions bubble up naturally
    signal = epics_signal_rw(int, args.pv_name, name="test")
