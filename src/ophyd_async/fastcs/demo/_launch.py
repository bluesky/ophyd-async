from argparse import ArgumentParser

from fastcs.launch import FastCS
from fastcs.transport.epics.ca.options import EpicsCAOptions
from fastcs.transport.epics.options import EpicsIOCOptions
from fastcs.transport.epics.pva.options import EpicsPVAOptions

from ophyd_async.fastcs.demo._demo import DemoController


# from fastcs.transport.tango.options import TangoDSROptions, TangoOptions
def main():
    parser = ArgumentParser()
    parser.add_argument("prefix", type=str)
    args = parser.parse_args()

    ca_options = EpicsCAOptions(ca_ioc=EpicsIOCOptions(pv_prefix=args.prefix))
    pva_options = EpicsPVAOptions(pva_ioc=EpicsIOCOptions(pv_prefix=args.prefix))
    # tango_options = TangoOptions(
    #     dsr=TangoDSROptions(dev_name=f"MY/DEVICE/{args.prefix}")
    # )
    launcher = FastCS(DemoController(), [ca_options, pva_options])
    launcher.run()


if __name__ == "__main__":
    main()
