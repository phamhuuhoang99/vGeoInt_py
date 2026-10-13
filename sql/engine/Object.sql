-------------------------------------------------------------------------------------------------------------------------
-- DOI TUONG
-------------------------------------------------------------------------------------------------------------------------
create table tbl_doituong
(
	id serial primary key,
	ten text not null,
	ido_phanloai varchar(8),
	unique(ten, ido_phanloai)
);
-- lay id doi tuong
create or replace function func_layid_doituong(p_tendoituong text, p_idophanloai varchar(8))
returns int as $$
	declare iddoituong int;
	begin
		iddoituong := (select tbl_doituong.id
						from tbl_doituong
						where lower(tbl_doituong.ten)=lower(p_tendoituong)
							and ido_phanloai = p_idophanloai);
		if iddoituong is null then
			iddoituong := -1;
		end if;
		return iddoituong;
	end
$$ language plpgsql;
-- them doi tuong
create or replace function func_them_doituong(p_tendoituong text, p_idophanloai varchar(8))
returns void as $$
	begin
		insert into tbl_doituong(ten, ido_phanloai) values(p_tendoituong, p_idophanloai)
		on conflict (ten, ido_phanloai) do nothing;
	end
$$ language plpgsql;
-- lay doi tuong
create or replace function func_lay_doituong(p_ido int)
returns table(id int, ten text, ido_phanloai varchar(8)) as $$
	begin
		return query
			select tbl_doituong.id, tbl_doituong.ten, tbl_doituong.ido_phanloai
			from tbl_doituong
			where tbl_doituong.id = p_ido;
	end
$$ language plpgsql;
--cap nhat
create or replace function func_sua_doituong(p_id int, p_tendoituong text)
returns void as $$
	begin
		update tbl_doituong set ten = p_tendoituong where id = p_id;
	end
$$ language plpgsql;
--
create or replace function func_sua_doituong(p_id int, p_tendoituong text, p_idophanloai varchar(8))
returns bool as $$
	begin
		if func_layid_doituong(p_tendoituong, p_idophanloai) = -1 then
			update tbl_doituong
			set ten = p_tendoituong,
				ido_phanloai = p_idophanloai
			where id = p_id;
			return true;
		end if;
		return false;
	end
$$ language plpgsql;
--Xoa doi tuong
create or replace function func_xoa_doituong(p_id int)
returns void as $$
	begin
		delete from tbl_doituong
		where tbl_doituong.id = p_id;
	end
$$ language plpgsql;
--lay tat ca doi tuong
create or replace function func_laytatca_doituong(p_idophanloai varchar(8))
returns table(id int, ten text) as $$
	begin
		return query
			select tbl_doituong.id, tbl_doituong.ten
			from tbl_doituong
			where tbl_doituong.ido_phanloai = p_idophanloai;
	end
$$ language plpgsql;
------------------------
--lay ten ido
-- GRP	GROUP
-- CLS	CLASS
-- TYP	TYPE
-- #	OJBECT
create or replace function func_lay_ten(p_ido varchar(8))
returns text as $$
	declare 
		rec record;
		code text;
		p_id int;
	
	begin
		code := substring(p_ido,1,3);
		p_id := substring(p_ido, 4)::int;
		if code = 'GRP' then
			select into rec ten from tbl_nhomdoituong where id = p_id;
		elsif code = 'CLS' then
			select into rec ten from tbl_loaidoituong where id = p_id;
		elsif code = 'TYP' then
			select into rec ten from tbl_kieudoituong where id = p_id;
		else
			select into rec ten from tbl_doituong where id = p_id;
		end if;
	return rec.ten;
	end
$$ language plpgsql;