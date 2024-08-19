
host=$(hostname | tr -cd '[:digit:]')
export eiger_ioc=EIGER-$host
export odin_ioc=ODIN-$host

mkdir /tmp/opi

podman run --rm -dt --net=host -v /tmp/opi/:/epics/opi ghcr.io/diamondlightsource/eiger-fastcs:0.1.0beta5 ioc $eiger_ioc

podman run --rm -dt --net=host -v /tmp/opi/:/epics/opi ghcr.io/diamondlightsource/odin-fastcs:0.2.0beta2 ioc $odin_ioc

sleep 1

pytest .

