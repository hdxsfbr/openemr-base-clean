# Project OpenEMR image: the pinned upstream release plus the co-pilot module.
# The image never contains evals/, docs/, tests/, docker/, or Terraform files
# (SEC-HIGH-500, AUDIT.md section 7.2); see the repository .dockerignore.
#
# Build from the repository root:
#   docker build -f infra/image/openemr.Dockerfile \
#     --build-arg MODULE_SRC=interface/modules/custom_modules/oe-module-copilot .
# Build on the Droplet (context prepared by deploy.sh):
#   docker compose build openemr
ARG OPENEMR_BASE=openemr/openemr:8.1.1@sha256:796adaa7b3d03c76902e9afd2c1b420afc39f040425a68d4aefdf4ace285fa0b
FROM ${OPENEMR_BASE}

ARG MODULE_SRC=oe-module-copilot
ARG MODULE_DEST=/var/www/localhost/htdocs/openemr/interface/modules/custom_modules/oe-module-copilot

COPY --chown=apache:apache ${MODULE_SRC} ${MODULE_DEST}
RUN find ${MODULE_DEST} -type d -exec chmod 0755 {} + \
    && find ${MODULE_DEST} -type f -exec chmod 0644 {} + \
    && chmod 0755 ${MODULE_DEST}/bin/register_module.php

LABEL org.opencontainers.image.title="AgentForge OpenEMR with Clinical Co-Pilot module" \
      org.opencontainers.image.source="https://labs.gauntletai.com/andrebatista/andrebatista-openemr-base-clean"
