#!/bin/bash
# Runs once, on an empty data volume (after the image's own 10_postgis.sh): builds the two databases
# from the original SQL scripts, in the order of the old vGeoEngine/SQL/init-db.bat.
set -e
export PGCLIENTENCODING=utf-8
run() { psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$1" -f "/sql/$2.sql"; }

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -c 'create database "vGeoCatalog"' -c 'create database "vGeoEngine"'
for f in command Countries Regions; do run vGeoCatalog "catalog/$f"; done
for f in Group Class Type Object Note Image ImageDetail Video VideoDetail Document DocumentDetail Account \
         Aircraft Ship Tank Rocket; do
    run vGeoEngine "engine/$f"
done
