# Job container for .github/workflows/ansible.yaml: the toolchain every run
# used to reinstall (Python, Ansible, Galaxy collections, op) baked in once.
# Tagged by a hash of this file + the requirements files, so any change here
# (or a Renovate bump) builds a fresh image on the next run.
FROM docker.io/1password/op:2.42.0@sha256:b0d7eebcb09bdc9d5862af91533e1851c968d4f969270c906f5da8c574f87e93 AS op

# Debian (glibc): the runner injects its node binary to run actions/checkout.
FROM docker.io/library/python:3.14-slim-trixie@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f

RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY --from=op /usr/local/bin/op /usr/local/bin/op

COPY requirements.txt requirements.yaml /tmp/ansible/
# requirements.txt is a uv hash lock of requirements.in: pip enforces the hashes.
RUN pip install --no-cache-dir --require-hashes -r /tmp/ansible/requirements.txt \
    && ansible-galaxy collection install -r /tmp/ansible/requirements.yaml -p /usr/share/ansible/collections \
    && rm -rf /tmp/ansible /root/.ansible

LABEL org.opencontainers.image.source="https://github.com/materia-ops/home-ops"
