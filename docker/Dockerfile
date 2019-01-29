# Download base image ubuntu 16.04
FROM ubuntu:16.04

ARG http_proxy
ARG https_proxy

env http_proxy $http_proxy
env https_proxy $https_proxy

RUN echo "deb http://archive.ubuntu.com/ubuntu xenial main universe" >> /etc/apt/sources.list; \
    echo "deb [trusted=yes] http://download.tizen.org/tools/latest-release/Ubuntu_16.04/ /" >> /etc/apt/sources.list; \
    apt-get update -y && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    binfmt-support \
    createrepo \
    curl \
    dh-make \
    libxml2-dev \
    mic \
    python \
    python-pip \
    python-all \
    python-configparser \
    python-igraph \
    python-iniparse \
    python-setuptools \
    qemu-arm-static \
    qemu-user-static \
    sudo \
    tar \
    vim \
    wget \
    yum \
    zlib1g-dev; \
    rm -rf /var/lib/apt/lists/*

ENV HOME /root
WORKDIR /opt/app

COPY ./ /opt/app/combirepo
COPY ./docker/requirements.txt /

RUN pip install -r /requirements.txt
RUN echo 'update-binfmts --enable' | tee -a /etc/profile /etc/bash.bashrc
RUN cd /opt/app/combirepo && python ./setup.py sdist && python ./setup.py install

CMD ["combirepo", "--help"]

EXPOSE 80 443
