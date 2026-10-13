-------------------------------------------------------------------------------------------------------------------------
-- GHI CHU
-------------------------------------------------------------------------------------------------------------------------

create table tbl_ghichu
(
	ido varchar(8) primary key,
	ghi_chu text
);
--lay
create or replace function func_lay_ghichu(p_ido varchar(8))
returns text as $$
	declare rec record;
	begin
		select into rec ghi_chu from tbl_ghichu where ido = p_ido;
		return rec.ghi_chu;
	end
$$ language plpgsql;
--them
create or replace function func_them_ghichu(p_ido varchar(8), p_ghichu text)
returns void as $$
	begin
		insert into tbl_ghichu(ido, ghi_chu) values(p_ido, p_ghichu);
	end
$$ language plpgsql;
--sua
create or replace function func_sua_ghichu(p_ido varchar(8), p_ghichu text)
returns void as $$
	begin
		insert into tbl_ghichu(ido, ghi_chu) values(p_ido, p_ghichu)
		on conflict (ido) do update set ghi_chu = excluded.ghi_chu;
	end
$$ language plpgsql;
--xoa
create or replace function func_xoa_ghichu(p_ido varchar(8))
returns void as $$
	begin
		delete from tbl_ghichu where ido = p_ido;
	end
$$ language plpgsql;
--