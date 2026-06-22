# Long-lived privileged "apptainer worker" container, one per CPU pod.
#
# dockerd creates exactly ONE of these per pod (no per-task churn); inside it the
# stdlib control server (server.py) runs every task env via `apptainer run`
# (read-only shared base from /sifs + ephemeral tmpfs overlay) -- daemon-less.
#
# Build (on a dockerd with internet, e.g. the CPU pod):
#   docker -H <pod> build -t mcp-universe/apptainer-worker:<tag> \
#       -f mcpuniverse/mcp/env_pool/apptainer_worker/Dockerfile \
#       mcpuniverse/mcp/env_pool/apptainer_worker
# Run: see scripts/bootstrap_apptainer_worker.sh (privileged + -p + NFS /sifs).
FROM python:3.11-slim

ARG APPTAINER_VERSION=1.5.1
# python:3.11-slim is Debian "trixie"; use the matching apptainer build.
ARG APPTAINER_DEB=apptainer_1.5.1-trixie%2B_amd64.deb

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates wget curl procps iproute2 \
        squashfs-tools libseccomp2 uidmap fakeroot cryptsetup-bin fuse2fs e2fsprogs \
    && wget -q "https://github.com/apptainer/apptainer/releases/download/v${APPTAINER_VERSION}/${APPTAINER_DEB}" -O /tmp/apptainer.deb \
    && (dpkg -i /tmp/apptainer.deb || apt-get install -f -y) \
    && rm -f /tmp/apptainer.deb \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && apptainer --version

COPY server.py /opt/apptainer_worker/server.py

ENV SIF_STORE=/sifs \
    APPTAINER_WORKER_PORT=8900 \
    APPTAINER_PID_NS=1
EXPOSE 8900
CMD ["python3", "/opt/apptainer_worker/server.py"]
