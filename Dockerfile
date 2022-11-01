ARG branch=stable
FROM cccs/assemblyline-v4-service-base:$branch

ENV SERVICE_PATH acce.acce_al.ACCE

WORKDIR /opt/al_service

# Copy service code
COPY . .

# Patch version in manifest
ARG version=4.0.0
USER root
RUN sed -i -e "s/\$SERVICE_TAG/$version/g" service_manifest.yml

# Switch to assemblyline user
USER assemblyline
