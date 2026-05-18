# syntax=docker/dockerfile:1
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026

FROM python:3.12-alpine

LABEL org.opencontainers.image.title="bsc-apm-mock-cas"
LABEL org.opencontainers.image.description="Mock CAS authentication service for the BSc APM Case Study testing environment."
LABEL org.opencontainers.image.licenses="GPL-3.0-or-later"

WORKDIR /opt/mock-cas

COPY pyproject.toml ./
COPY src/ ./src/
COPY fixtures/ ./fixtures/
COPY cas-config.json /etc/mock-cas/cas-config.json

RUN pip install --no-cache-dir .

ENV MOCK_CAS_CONFIG=/etc/mock-cas/cas-config.json \
    MOCK_CAS_PORT=8082 \
    MOCK_CAS_FIXTURES_DIR=/opt/mock-cas/fixtures

EXPOSE 8082

CMD ["python", "-m", "mock_cas.server"]
