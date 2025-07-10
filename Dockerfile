# The devcontainer should use the developer target and run as root with podman
# or docker with user namespaces.
FROM ubuntu:24.04 AS developer

# Add any system dependencies for the developer/build environment here
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    git \
    graphviz \
    libxcb-cursor0 \
    man \
    qt6-base-dev \
    software-properties-common \
    ssh-client \
    && rm -rf /var/lib/apt/lists/*

# Copy in the default bash configuration
# This can be overridden by the user mounting a different folder over the top
COPY .devcontainer/terminal-config /root/terminal-config
ENV USER_TERMINAL_CONFIG=/user-terminal-config
RUN /root/terminal-config/ensure-user-terminal-config.sh

# Install uv using the official image
# See https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /uvx /bin/
