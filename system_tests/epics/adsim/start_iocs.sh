#!/usr/bin/env bash

set -xe

# Override these if needed (export SERVICES_REPO=..., etc.)
SERVICES_REPO="https://github.com/epics-containers/example-services.git"
SERVICES_VERSION="main"
SERVICES_REPO_LOCAL="build/example-services"

COMPOSE_FILE="${SERVICES_REPO_LOCAL}/compose.yaml"

# Ensure a fresh copy of the example services
rm -rf ${SERVICES_REPO_LOCAL}
mkdir -p ${SERVICES_REPO_LOCAL}
git clone ${SERVICES_REPO} ${SERVICES_REPO_LOCAL} -b ${SERVICES_VERSION}

# Run IOCs
docker compose -f ${COMPOSE_FILE} up -d
