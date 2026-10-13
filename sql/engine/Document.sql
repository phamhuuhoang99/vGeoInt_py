-------------------------------------------------------------------------------------------------------------------------
-- TAI LIEU
-------------------------------------------------------------------------------------------------------------------------

create table tbl_tailieu
(
	id serial primary key,
	duong_dan text unique not null
);
--Hàm cho phép lấy id tài liệu khi biết đường dẫn
create or replace function func_layid_tailieu(p_duongdan text)
returns int as $$
	declare idtailieu int;
	begin
		idtailieu := (select tbl_tailieu.id
						from tbl_tailieu
						where lower(tbl_tailieu.duong_dan) = lower(p_duongdan));
		if idtailieu is null then
			idtailieu := -1;
		end if;
		return idtailieu;
	end
$$ language plpgsql;
--Hàm thêm tài liệu khi có đường dẫn
create or replace function func_them_tailieu(p_duongdan text)
returns bool as $$
	begin
		if func_layid_tailieu(p_duongdan) = -1 then
			insert into tbl_tailieu(duong_dan) values(p_duongdan);
			return true;
		end if;
		return false;
	end
$$ language plpgsql;
--Hàm xóa tài liệu 
create or replace function func_xoa_tailieu(p_idtailieu int)
returns void as $$
	begin
		delete from tbl_tailieu where id = p_idtailieu;
	end
$$ language plpgsql;