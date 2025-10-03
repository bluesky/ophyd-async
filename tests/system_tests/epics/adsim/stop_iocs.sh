#!/usr/bin/env bash

set -xe

THIS_DIR=$(realpath $(dirname ${0}))
REPO_ROOT="${THIS_DIR}/../../.."
SERVICES_REPO_LOCAL="${REPO_ROOT}/example-services"
COMPOSE_FILE="${SERVICES_REPO_LOCAL}/compose.yaml"

# Ensure the example services are present
git submodule init

# Shut down IOCs
docker compose -f ${COMPOSE_FILE} down
