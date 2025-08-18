#!/usr/bin/env bash

set -xe

THIS_DIR=$(realpath $(dirname ${0}))
REPO_ROOT="${THIS_DIR}/../../.."
SERVICES_REPO_LOCAL="${REPO_ROOT}/example-services"
COMPOSE_FILE="${SERVICES_REPO_LOCAL}/compose.yaml"

# Take down any IOCs that are already running
${REPO_ROOT}/system_tests/epics/adsim/stop_iocs.sh

# Run fresh IOCs
docker compose -f ${COMPOSE_FILE} up -d
