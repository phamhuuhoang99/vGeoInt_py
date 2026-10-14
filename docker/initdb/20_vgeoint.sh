#!/bin/bash
# Runs once, on an empty data volume (after the image's own 10_postgis.sh).
# vGeoCatalog: built from the original SQL scripts.
# vGeoEngine: the data dump of the old installer (sql/engine/init_vgeoengine.sql: schema + objects, images,
# videos, documents, accounts). It was made by pg_dump 17: drop the PG17-only "SET transaction_timeout".
set -e
export PGCLIENTENCODING=utf-8
run() { psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$1" -f "/sql/$2.sql"; }

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -c 'create database "vGeoCatalog"' -c 'create database "vGeoEngine"'
for f in command Countries Regions; do run vGeoCatalog "catalog/$f"; done
grep -v '^SET transaction_timeout' /sql/engine/init_vgeoengine.sql \
    | psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d vGeoEngine > /dev/null
