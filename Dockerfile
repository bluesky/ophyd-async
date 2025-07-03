# The devcontainer should use the developer target and run as root with podman
# or docker with user namespaces.
FROM ubuntu:24.04 AS developer

# Add any system dependencies for the developer/build environment here
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    graphviz \
    libxcb-cursor0 \
    qt6-base-dev \
    software-properties-common \
    ssh-client \
    && rm -rf /var/lib/apt/lists/*

# Install uv using the official image
# See https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
ARG UV_VERSION=0.7
COPY --from=ghcr.io/astral-sh/uv:${UV_VERSION} /uv /uvx /bin/

# Make a blank venv with the required Python version
ARG PYTHON_VERSION=3.11
RUN uv venv --python=python${PYTHON_VERSION} /venv
ENV PATH=/venv/bin:$PATH
