#!/bin/sh
# Local / manual-test entrypoint ONLY — continuo never runs it.
#
# When continuo drives this image (compile, candidate seed-build, or a scheduled
# run) it sets the container's `command` in the Kubernetes pod spec, which
# overrides this Docker ENTRYPOINT. This script exists purely so the image is
# runnable by hand for local debugging, e.g.:
#   docker run -e TABLE_NAME=<model> <project-image>
set -e

: "${TABLE_NAME:?TABLE_NAME must be set}"

echo "schedule_name=${SCHEDULE_NAME} table_name=${TABLE_NAME} schema_name=${SCHEMA} job_name=${JOB_NAME} project_name=${PROJECT_NAME}"

exec dbt run --select "${TABLE_NAME}" --profiles-dir /project
