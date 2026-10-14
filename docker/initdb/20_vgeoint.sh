#!/bin/bash
# Runs once, on an empty data volume (after the image's own 10_postgis.sh): loads the data dumps of the
# old installer (sql/catalog/init_vgeocatalog.sql, sql/engine/init_vgeoengine.sql: schema + data).
# They were made by pg_dump 17: drop the PG17-only "SET transaction_timeout" for this PostgreSQL 16 server.
set -eo pipefail
export PGCLIENTENCODING=utf-8
load() {
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -c "create database \"$1\""
    grep -v '^SET transaction_timeout' "/sql/$2" | psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$1" > /dev/null
}

load vGeoCatalog catalog/init_vgeocatalog.sql
load vGeoEngine engine/init_vgeoengine.sql
