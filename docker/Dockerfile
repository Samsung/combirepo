# Download base image ubuntu 16.04
FROM ubuntu:16.04

ARG http_proxy
ARG https_proxy

env http_proxy $http_proxy
env https_proxy $https_proxy

RUN echo "deb http://archive.ubuntu.com/ubuntu xenial main universe" >> /etc/apt/sources.list
RUN echo "deb [trusted=yes] http://download.tizen.org/tools/latest-release/Ubuntu_16.04/ /" >> /etc/apt/sources.list

RUN apt-get update -y
RUN apt-get upgrade -y
RUN apt-get install -y \
    binfmt-support \
    createrepo \
    curl \
    dh-make \
    git \
    libxml2-dev \
    mic \
    python \
    python-pip \
    python-all \
    python-configparser \
    python-igraph \
    python-iniparse \
    qemu-arm-static \
    qemu-user-static \
    sudo \
    tar \
    vim \
    wget \
    yum \
    zlib1g-dev

ENV HOME /root
WORKDIR /opt/app

COPY ./ /opt/app/combirepo
COPY ./docker/requirements.txt /
COPY ./docker/combirepo_update.sh /

RUN pip install --upgrade pip
RUN pip install -r /requirements.txt
RUN chmod +x /combirepo_update.sh
RUN echo 'update-binfmts --enable' | tee -a /etc/profile /etc/bash.bashrc
RUN cd /opt/app/combirepo && git submodule init && git submodule update
RUN /combirepo_update.sh

CMD ["combirepo", "--help"]

EXPOSE 80 443
