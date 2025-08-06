#!/usr/bin/env bash

set -xe

# Override these if needed (export SERVICES_REPO=..., etc.)
SERVICES_REPO_LOCAL="build/example-services"

COMPOSE_FILE="${SERVICES_REPO_LOCAL}/compose.yaml"

# Run IOCs
docker compose -f ${COMPOSE_FILE} down
