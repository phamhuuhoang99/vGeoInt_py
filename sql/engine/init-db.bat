@echo off
set PGPASSWORD=%1
if [%PGPASSWORD%] == [] exit /B 1
set USER=%2
if [%USER%] == [] set USER=postgres
set PGBIN=%3
if [%PGBIN%] == [] set PGBIN=C:\Program Files\PostgreSQL\10\bin
set PATH=%PATH%;%PGBIN%
set DBNAME=vGeoEngine
set PGCLIENTENCODING=utf-8
chcp 65001
createdb -U %USER% %DBNAME%
psql -U %USER% -d %DBNAME% -f Group.sql
psql -U %USER% -d %DBNAME% -f Class.sql
psql -U %USER% -d %DBNAME% -f Type.sql
psql -U %USER% -d %DBNAME% -f Object.sql
psql -U %USER% -d %DBNAME% -f Note.sql
psql -U %USER% -d %DBNAME% -f Image.sql
psql -U %USER% -d %DBNAME% -f ImageDetail.sql
psql -U %USER% -d %DBNAME% -f Video.sql
psql -U %USER% -d %DBNAME% -f VideoDetail.sql
psql -U %USER% -d %DBNAME% -f Document.sql
psql -U %USER% -d %DBNAME% -f DocumentDetail.sql
psql -U %USER% -d %DBNAME% -f Account.sql
psql -U %USER% -d %DBNAME% -f Aircraft.sql
psql -U %USER% -d %DBNAME% -f Ship.sql
psql -U %USER% -d %DBNAME% -f Tank.sql
psql -U %USER% -d %DBNAME% -f Rocket.sql
exit