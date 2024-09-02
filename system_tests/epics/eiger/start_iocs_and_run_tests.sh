
host=$(hostname | tr -cd '[:digit:]')
export eiger_ioc=EIGER-$host
export odin_ioc=ODIN-$host

mkdir /tmp/opi

if command -v docker &> /dev/null; then
    DOCKER_COMMAND=docker
else
    DOCKER_COMMAND=podman
fi

echo "Using $DOCKER_COMMAND" 

$DOCKER_COMMAND run --rm --name=$eiger_ioc -dt --net=host -v /tmp/opi/:/epics/opi ghcr.io/diamondlightsource/eiger-fastcs:0.1.0beta5 ioc $eiger_ioc

$DOCKER_COMMAND run --rm --name=$odin_ioc -dt --net=host -v /tmp/opi/:/epics/opi ghcr.io/diamondlightsource/odin-fastcs:0.2.0beta2 ioc $odin_ioc

sleep 1

pytest .

podman kill $eiger_ioc
podman kill $odin_ioc
