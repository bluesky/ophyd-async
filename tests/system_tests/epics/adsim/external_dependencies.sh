#!/usr/bin/env bash

# skip notice: -y

echo -n "$(tput setaf 3)"

if command -v podman > /dev/null 2>&1; then
    PODMAN_CLI=podman
elif command -v docker > /dev/null 2>&1; then
    PODMAN_CLI=docker  # fallback to docker
else
    echo "Error: Neither podman nor docker command found." >&2
    exit 1
fi
echo "Using container CLI: $PODMAN_CLI"

THIS_DIR=$(realpath $(dirname "${0}"))
REPO_ROOT="${THIS_DIR}/../../../.."
SERVICES_REPO_LOCAL="${REPO_ROOT}/example-services"
COMPOSE_FILE="${SERVICES_REPO_LOCAL}/compose.yaml"

# Run fresh IOCs
if [[ "${1:-}" != "-y" ]]; then
    echo -n "$(tput bold)"
    echo "Note: To stop the services, press Ctrl+C."
    echo "$(tput sgr0)$(tput setaf 3)"
    read -p "Press return to start the services now..."
fi

echo "$(tput sgr0)"

$PODMAN_CLI compose -f "$COMPOSE_FILE" up ca-gateway bl01t-di-cam-01
