# The devcontainer should use the developer target and run as root with podman
# or docker with user namespaces.
FROM ghcr.io/diamondlightsource/ubuntu-devcontainer:noble AS developer

ENV DOCKER=docker-28.5.1
ENV DOCKER_COMPOSE_RELEASE_TAG=v2.40.3

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

# install docker-compose plugin
RUN mkdir -p /usr/libexec/docker/cli-plugins/ && \
    curl -SL https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_RELEASE_TAG}/docker-compose-linux-x86_64 -o /usr/libexec/docker/cli-plugins/docker-compose && \
    chmod +x /usr/libexec/docker/cli-plugins/docker-compose
