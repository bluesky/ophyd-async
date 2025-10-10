# The devcontainer should use the developer target and run as root with podman
# or docker with user namespaces.
FROM ghcr.io/diamondlightsource/ubuntu-devcontainer:noble AS developer

ENV DOCKER=docker-27.3.1

# Add any system dependencies for the developer/build environment here
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    graphviz \
    libxcb-cursor0 \
    qt6-base-dev \
    curl \
    && apt-get dist-clean

# install the docker ce cli binary
RUN curl -O https://download.docker.com/linux/static/stable/x86_64/${DOCKER}.tgz && \
    tar xvf ${DOCKER}.tgz && \
    cp docker/docker /usr/bin && \
    rm -r ${DOCKER}.tgz docker
