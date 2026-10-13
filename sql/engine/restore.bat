@echo off
set PGPASSWORD=%1
if [%PGPASSWORD%] == [] exit /B 1
set USER=%2
if [%USER%] == [] set USER=postgres
set PGBIN=%3
if [%PGBIN%] == [] set PGBIN=C:\Program Files\PostgreSQL\14\bin
set PATH=%PATH%;%PGBIN%
set DBNAME=vGeoEngine
set PGCLIENTENCODING=utf-8
chcp 65001
pg_restore -U %USER% -j 8 -d %DBNAME% vGeoEngine.vGeoBak
echo CSDL khôi phục xong