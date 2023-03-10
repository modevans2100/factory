# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

FROM python:3.7
LABEL maintainer="Liang-Chieh Chen <jamesqaq@google.com>"

RUN apt-get update && apt-get install -y \
    bzip2 \
    cgpt \
    curl \
    gcc \
    git \
    libssl-dev \
    lsb-release \
    moreutils \
    nginx \
    pbzip2 \
    pigz \
    rsync \
    sharutils \
    sudo \
    unzip \
    vboot-utils \
    vim \
    xz-utils

COPY docker/requirements.txt /root/
RUN pip install -r /root/requirements.txt

# Install gcloud command.
ARG gcloud_archive_name="google-cloud-sdk-245.0.0-linux-x86_64.tar.gz"
RUN cd /usr/src/ && \
  wget "https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/${gcloud_archive_name}" && \
  tar xvf "${gcloud_archive_name}" && \
  google-cloud-sdk/install.sh --rc-path /root/.bashrc --quiet && \
  rm "${gcloud_archive_name}" && \
  ln -s /usr/src/google-cloud-sdk/bin/gcloud /usr/bin/gcloud && \
  ln -s /usr/src/google-cloud-sdk/bin/gsutil /usr/bin/gsutil

# Install factory toolkit.
ARG GS_BASE="gs://chromeos-releases/dev-channel"
ARG BOARD="grunt"
ARG VERSION="13371.0.0"
ARG TOOLKIT="${GS_BASE}/${BOARD}/${VERSION}/*-factory-*.zip"
COPY docker/service_account.json /
RUN gcloud auth activate-service-account --key-file=/service_account.json && \
    gsutil cp "${TOOLKIT}" /tmp/factory.zip && \
    unzip -o /tmp/factory.zip toolkit/install_factory_toolkit.run -d /tmp && \
    /tmp/toolkit/install_factory_toolkit.run -- --non-cros --yes

ENV PYTHONPATH=/usr/local/factory/py_pkg
ENV GOOGLE_APPLICATION_CREDENTIALS=/service_account.json

# Set user name for finalize_bundle.
ENV USER bundle_creator

COPY . /usr/local/factory/py/bundle_creator/

CMD gcloud auth activate-service-account --key-file=/service_account.json && \
    python /usr/local/factory/py/bundle_creator/docker/worker.py
