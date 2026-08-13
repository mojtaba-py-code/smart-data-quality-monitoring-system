# Container image for running DQMS on a schedule - a cron entry, a Kubernetes
# CronJob, or a CI step - without installing Python on the host.
#
# Build:  docker build -t dqms:1.2.0 .
# Run:    docker run --rm -v "$PWD/data:/data:ro" -v "$PWD/output:/output" \
#             dqms:1.2.0 analyze /data/customers.csv

# --------------------------------------------------------------------------
# Stage 1: build a wheel, so the runtime image carries no build tooling.
# --------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade pip build \
 && python -m build --wheel --outdir /dist

# --------------------------------------------------------------------------
# Stage 2: runtime.
# --------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    # Paths point at the mounted volumes rather than the image, so nothing the
    # container writes ends up in a layer.
    DQMS_PATHS__INPUT_DIR=/data \
    DQMS_PATHS__OUTPUT_DIR=/output \
    DQMS_PATHS__LOG_DIR=/output/logs \
    DQMS_PATHS__HISTORY_DB=/output/history.db

# Run as an unprivileged account. A data-quality job reads files it did not
# write; there is no reason for it to hold root inside the container.
RUN useradd --system --uid 10001 --create-home --home-dir /home/dqms dqms \
 && mkdir -p /data /output \
 && chown -R dqms:dqms /data /output

COPY --from=build /dist/*.whl /tmp/
RUN python -m pip install --no-cache-dir /tmp/*.whl \
 && rm -f /tmp/*.whl

# The default configuration file; override it by mounting your own over this
# path, or with DQMS_* environment variables.
COPY --chown=dqms:dqms config/config.yaml /etc/dqms/config.yaml

USER dqms
WORKDIR /work
VOLUME ["/data", "/output"]

# No secrets are baked into the image. The alert webhook URL, if used, is passed
# at run time with -e DQMS_ALERTS__WEBHOOK_URL=... so it never enters a layer.
ENTRYPOINT ["dqms", "--config", "/etc/dqms/config.yaml"]
CMD ["--help"]
