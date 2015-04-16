#!/bin/bash
#
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#

. "$(dirname "$(readlink -f "$0")")/common.sh" || exit 1

UMPIRE_CONTAINER_NAME="umpire"
UMPIRE_IMAGE_NAME="cros/umpire"

DIRBASE="$(dirname "$(readlink -f "$0")")"
BUILDDIR=${DIRBASE}/../misc/umpire_docker
SDKROOT=${DIRBASE}/../../../..
KEYDIR=${SDKROOT}/src/scripts/mod_for_test_scripts/ssh_keys
KEYFILE=${KEYDIR}/testing_rsa

check_status() {
  local container_name="$1"
  local status="$(sudo docker ps | grep ${container_name} | grep Up)"

  if [ -z "${status}" ]; then
    die "${UMPIRE_CONTAINER_NAME} container is not running"
  fi
}

get_container_IP() {
  local container_name="$1"
  check_status "${container_name}"

  sudo docker inspect "${container_name}" | \
    awk '/IPAddress/ { gsub(/[",]/, "", $2); print $2 }'
}

do_ssh() {
  local container_name="$1"
  check_status "${container_name}"
  shift

  local ip="$(get_container_IP ${container_name})"
  ssh -o StrictHostKeyChecking=no -i ${KEYFILE} root@${ip} $@
}

do_build() {
  # docker build requires resource to be in the build directory, copy keyfile
  # for using as authorized_keys
  cp ${KEYDIR}/testing_rsa.pub ${BUILDDIR}/authorized_keys

  sudo docker build -t ${UMPIRE_IMAGE_NAME} ${BUILDDIR}
  if [ $? -eq 0 ]; then
    echo "${UMPIRE_CONTAINER_NAME} container successfully built."
  fi

  # Cleanup
  rm ${BUILDDIR}/authorized_keys
}

do_destroy() {
  echo -n "Deleting ${UMPIRE_CONTAINER_NAME} container ... "
  sudo docker stop "${UMPIRE_CONTAINER_NAME}" >/dev/null 2>&1
  sudo docker rm "${UMPIRE_CONTAINER_NAME}" >/dev/null 2>&1
  echo "done"
}

do_start() {
  echo -n "Starting ${UMPIRE_CONTAINER_NAME} container ... "
  sudo docker run -d \
    -p 4455:4455 \
    -p 9000:9000 \
    -p 8082:8082 \
    -p 8086:8086 \
    -v ${SDKROOT}:/mnt \
    --name "${UMPIRE_CONTAINER_NAME}" \
    "${UMPIRE_IMAGE_NAME}" >/dev/null 2>&1

  # Container is already created, run the container instead
  if [ $? -ne 0 ]; then
    sudo docker start "${UMPIRE_CONTAINER_NAME}" >/dev/null 2>&1
  fi
  echo "done"

  echo -e '\n*** NOTE ***'
  echo '- Chromium source directory is mounted under /mnt.'
  echo '- Umpire service ports 8082, 8086 is mapped to the local machine.'
  echo '- Overlord service ports 4455, 9000 is mapped to the local machine.'
}

do_stop() {
  echo -n "Stopping ${UMPIRE_CONTAINER_NAME} container ... "
  sudo docker stop "${UMPIRE_CONTAINER_NAME}" >/dev/null 2>&1
  echo "done"
}

do_install() {
  local container_name="$1"
  local board="$2"
  local toolkit="$3"
  check_status "${container_name}"

  if [ ! -e "${toolkit}" ]; then
    die "Factory toolkit '${toolkit}' does not exist, abort."
  fi

  local ip=$(get_container_IP "${UMPIRE_CONTAINER_NAME}")
  scp -o StrictHostKeyChecking=no -i ${KEYFILE} ${toolkit} root@${ip}:/tmp
  ssh -o StrictHostKeyChecking=no -i ${KEYFILE} root@${ip} \
    /tmp/${toolkit##*/} -- --init-umpire-board=${board}
  ssh -o StrictHostKeyChecking=no -i ${KEYFILE} root@${ip} \
    "echo export BOARD=$board >> /root/.bashrc"
}

usage() {
  cat << __EOF__
Usage: $0 COMMAND [arg ...]

Commands:
    build       build umipre container
    destroy     destroy umpire container
    start       start umpire container
    stop        stop umpire container
    ssh         ssh into umpire container
    ip          get umpire container IP
    install     install factory toolkit
    help        Show this help message

Sub-Command options:
    install     BOARD FACTORY_TOOLKIT_FILE
    ssh         SSH_ARGS

Options:
    -h, --help  Show this help message
__EOF__
}

main() {
  case "$1" in
    build)
      do_build
      ;;
    destroy)
      do_destroy
      ;;
    start)
      do_start
      ;;
    stop)
      do_stop
      ;;
    ssh)
      shift
      do_ssh "${UMPIRE_CONTAINER_NAME}" "$@"
      ;;
    ip)
      get_container_IP "${UMPIRE_CONTAINER_NAME}"
      ;;
    install)
      shift
      do_install "${UMPIRE_CONTAINER_NAME}" "$@"
      ;;
    *|help|-h|--help)
      usage
      ;;
  esac
}

main "$@"
