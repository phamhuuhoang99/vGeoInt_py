create extension postgis;

create table library(
	id serial primary key,
	name text unique not null, 
	filters text
);

create table directory(
	id serial primary key,
	path text not null,
	enabled boolean,
	idlib integer references library(id) on delete cascade
);

----
create table geodata(
	id serial primary key,
	filename text not null,
	datetime timestamp,
	extent text,
	coordinatesystem text,
	srid integer,
	geom geometry,
	idlib integer references library(id) on delete cascade, 
	unique (filename, idlib)
);

----
create or replace function is_exists_library(name_ text)
returns boolean as $$
declare
	ret_id integer;
	
begin
	select id into ret_id from library where name=name_;
	if ret_id is null then
		return false;
	else
		return true;
	end if;
end
$$ language plpgsql;

----
create or replace function insert_library(name_ text, filters_ text)
returns void as $$
declare
	isexists boolean;
	
begin
	isexists := (select is_exists_library(name_));
	
	if isexists = true then
		update library set filters = filters_ where name = name_;
	else
		insert into library(name, filters) values(name_, filters_);
	end if;
end
$$ language plpgsql;

----
create or replace function remove_library(name_ text)
returns void as $$
begin
	delete from library where name = name_;
end
$$ language plpgsql;

----
create or replace function is_exists_directory(path_ text, idlib_ integer)
returns boolean as $$
declare
	ret_id integer;
	
begin
	select id into ret_id from directory where path = path_ and idlib = idlib_;
	if ret_id is null then
		return false;
	else
		return true;
	end if;
end
$$ language plpgsql;

----
create or replace function insert_directory(path_ text, enabled_ boolean, idlib_ integer)
returns void as $$
declare
	isexists boolean;
begin
	isexists := (select is_exists_directory(path_, idlib_));
	if isexists = true then
		update directory set enabled = enabled_ where path = path_ and idlib = idlib_;
	else
		insert into directory(path, enabled, idlib) values(path_, enabled_, idlib_);
	end if;
end
$$ language plpgsql;

----
create or replace function remove_directory(path_ text, idlib_ integer)
returns void as $$
begin
	delete from directory where path = path_ and idlib = idlib_;
end
$$ language plpgsql;

--
create or replace function is_exists_geodata(filename_ text, idlib_ integer)
returns boolean as $$
declare
	ret_id integer;
begin
	select id into ret_id from geodata where filename = filename_ and idlib = idlib_;
	if ret_id is null then
		return false;
	else
		return true;
	end if;
end
$$ language plpgsql;

--
create or replace function insert_geodata(filename_ text, datetime_ timestamp,
										  extent_ text, coordinatesystem_ text,
										  srid_ integer, geom_ text, idlib_ integer)
returns void as $$
declare
	isexists boolean;
begin
	isexists := (select is_exists_geodata(filename_, idlib_));
	if isexists = true then
		update geodata set
			datetime = datetime_,
			extent = extent_,
			coordinatesystem = coordinatesystem_,
			srid = srid_,
			geom = geom_
		where filename = filename_ and idlib = idlib_;
	else
		insert into geodata(filename, datetime, extent, coordinatesystem, srid, geom, idlib)
		values (filename_, datetime_, extent_, coordinatesystem_, srid_, geom_, idlib_);
	end if;
end
$$ language plpgsql;

--
create or replace function remove_geodata(filename_ text, idlib_ integer)
returns void as $$
begin
	delete from geodata where filename = filename_ and idlib = idlib_;
end
$$ language plpgsql;

--
create or replace function createview_searcharea(
	numeric(16,8), numeric(16,8), numeric(16,8), numeric(16,8), integer, text)
returns void as $$
begin
	execute 'create or replace view searcharea as '
			'select geodata.id, filename, datetime, extent, coordinatesystem, library.name, geom '
			'from geodata, library '
			'where library.id = idlib and idlib = ' ||$5|| ' '
			'and ' ||$6|| '(ST_MakeEnvelope(' ||$1||',' ||$2||',' ||$3||',' ||$4||', 4326), geom)';
end
$$ language plpgsql;

--
create or replace function createview_searchcountry(text, text)
returns void as $$
begin
	execute 'create or replace view searchcountry as ' ||
			'select geodata.id, filename, datetime, extent, ' ||
			'coordinatesystem, geodata.geom, library.name ' ||
			'from geodata, countryshp, library ' ||
			'where countryshp.name=' || quote_literal($1) || ' and idlib = library.id ' ||
			'and ' ||$2|| '(countryshp.geom, geodata.geom)';
end
$$ language plpgsql;
--
create or replace function createview_searchregion(text, text)
returns void as $$
begin
	execute 'create or replace view searchregion as ' ||
			'select geodata.id, filename, datetime, extent, ' ||
			'coordinatesystem, geodata.geom, library.name ' ||
			'from geodata, regionshp, library ' ||
			'where region=' || quote_literal($1) || ' and idlib = library.id ' ||
			'and ' ||$2|| '(regionshp.geom, geodata.geom)';
end
$$ language plpgsql;
