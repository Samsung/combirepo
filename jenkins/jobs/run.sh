#!/bin/bash

# install dependencies
sudo apt-get install --yes yum python-igraph python-iniparse zlib1g-dev libxml2-dev mic createrepo python-pip qemu-user-static python-configparser python-all dh-make

sudo ./setup.py build
sudo ./setup.py install

packages_url=`sed "s/\.ks/\.packages/g" <<<"${KICKSTART_FILE}"`
ks_file="local.ks"
pkg_tmp="tmp.packages"
pkg_file="local.packages"
log_file="local.log"

wget ${KICKSTART_FILE} -O ${ks_file} --user ${SPIN_USER} --password ${SPIN_USR}
wget ${packages_url} -O ${pkg_tmp} --user ${SPIN_USER} --password ${SPIN_PSW}

if [ ! -f ${ks_file} ]; then
    echo "Kickstart file not found!"
    exit -1
fi

if [ ! -f ${pkg_tmp} ]; then
    echo "Packages file not found!"
    exit -1
else
	cat ${pkg_tmp} | awk '{print $1}' | sed -e "s|\.${ARCH}||g" | sed -e "s|\.noarch||g" | sort -n > ${pkg_file}
fi

unified_repo=`cat ${ks_file} | grep 'repo --name=unified-standard --baseurl=' | egrep -o 'https?://[^ ]+'`
unified_asan_repo=`cat ${ks_file} | grep 'repo --name=unified-standard-asan --baseurl=' | egrep -o 'https?://[^ ]+'`
base_repo=`cat ${ks_file} | grep 'repo --name=base-standard --baseurl=' | egrep -o 'https?://[^ ]+'`
base_asan_repo=`cat ${ks_file} | grep 'repo --name=base-standard-asan --baseurl=' | egrep -o 'https?://[^ ]+'`

if ${MIRROR}; then mirror="--mirror"; else mirror=""; fi
if ${GREEDY}; then greedy="--greedy"; else greedy=""; fi
if ${DEBUG}; then debug="--debug"; else debug=""; fi
if ${VERBOSE}; then verbose="--verbose"; else verbose=""; fi

sudo rm -f ${log_file}
mkdir -p ${OUTDIR}
mkdir -p ${CACHEDIR}

sudo combirepo -A ${ARCH} -k ${ks_file} --packages-file ${pkg_file} --user ${SPIN_USER} --password ${SPIN_PWD} -o ${OUTDIR} \
-l ${log_file} --tmp-dir ${CACHEDIR} -j ${JOBS_NUMBER} \
${greedy} ${mirror} ${debug} ${verbose} \
--regenerate-repodata --preferring-strategy big --skip-version-mismatch \
-p terminfo-base-full,glibc-asan \
unified-standard ${unified_repo} ${unified_asan_repo} \
unified-standard-asan ${unified_repo} ${unified_asan_repo} \
base-standard ${base_repo} ${base_asan_repo} \
base-standard-asan ${base_repo} ${base_asan_repo}
