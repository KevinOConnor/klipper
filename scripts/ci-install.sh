#!/bin/bash
# Build setup script for continuous integration testing.
# See ci-build.sh for the actual test steps.

# Stop script early on any error; check variables; be verbose
set -eux

MAIN_DIR=${PWD}
BUILD_DIR=${PWD}/ci_build
CACHE_DIR=${PWD}/ci_cache
mkdir -p ${BUILD_DIR} ${CACHE_DIR}


######################################################################
# Install system dependencies
######################################################################

echo -e "\n\n=============== Install system dependencies\n\n"
PKGS="virtualenv python-dev libffi-dev build-essential"
PKGS="${PKGS} gcc-avr avr-libc"
PKGS="${PKGS} libnewlib-arm-none-eabi gcc-arm-none-eabi binutils-arm-none-eabi"
PKGS="${PKGS} pv libmpfr-dev libgmp-dev libmpc-dev texinfo bison flex"
sudo apt-get install ${PKGS}


######################################################################
# Install (or build) pru gcc
######################################################################

echo -e "\n\n=============== Install embedded pru gcc\n\n"
PRU_FILE=${CACHE_DIR}/gnupru.tar.gz
PRU_DIR=${BUILD_DIR}/pru-gcc

if [ ! -f ${PRU_FILE} ]; then
    cd ${BUILD_DIR}
    git config --global user.email "you@example.com"
    git config --global user.name "Your Name"
    git clone https://github.com/dinuxbg/gnupru -b 2018.03-beta-rc3 --depth 1
    cd gnupru
    export PREFIX=${PRU_DIR}
    ./download-and-patch.sh 2>&1 | pv -nli 30 > ${BUILD_DIR}/gnupru-build.log
    ./build.sh 2>&1 | pv -nli 30 >> ${BUILD_DIR}/gnupru-build.log
    cd ${BUILD_DIR}
    tar cfz ${PRU_FILE} pru-gcc/
else
    cd ${BUILD_DIR}
    tar xfz ${PRU_FILE}
fi


######################################################################
# Create python virtualenv environment
######################################################################

echo -e "\n\n=============== Install python virtualenv\n\n"
cd ${MAIN_DIR}
virtualenv -p python3 ${BUILD_DIR}/python-env
${BUILD_DIR}/python-env/bin/pip install -r ${MAIN_DIR}/scripts/klippy-requirements.txt
