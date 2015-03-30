FROM ubuntu:14.04
MAINTAINER v.barinov@samsung.com

RUN echo "## Tizen software\ndeb http://download.tizen.org/tools/latest-release/Ubuntu_14.04 /" >> /etc/apt/sources.list
RUN apt-get dist-upgrade -y
RUN apt-get update -y
RUN apt-get upgrade -y
RUN apt-get install yum python-igraph python-iniparse zlib1g-dev libxml2-dev mic createrepo python-pip qemu-user-static -y --force-yes --fix-missing
RUN sed -e 's/arm64/aarch64/;/qemu_arm_string.*aarch64/s/":aarch64:.*"/":aarch64:M::\\\\x7fELF\\\\x02\\\\x01\\\\x01\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x02\\\\x00\\\\xb7:\\\\xff\\\\xff\\\\xff\\\\xff\\\\xff\\\\xff\\\\xff\\\\x00\\\\xff\\\\xff\\\\xff\\\\xff\\\\xff\\\\xff\\\\xff\\\\xff\\\\xfe\\\\xff\\\\xff:%s:\\n"/' -i /usr/share/pyshared/mic/utils/misc.py

COPY combirepo.tar.gz /root/combirepo.tar.gz
RUN mkdir /root/combirepo/ && tar xf /root/combirepo.tar.gz -C /root/combirepo/ --strip-components=1
RUN cd /root/combirepo && pip install -e .
