-------------------------------------------------------------------------------------------------------------------------
-- HINH ANH
-------------------------------------------------------------------------------------------------------------------------
create table tbl_hinhanh
(
	id serial primary key,
	duong_dan text unique not null,
	hinhanh_thunho text 
);
--Hàm lấy id của ảnh khi biết đường dẫn
create or replace function func_layid_hinhanh(p_duongdan text)
returns int as $$
	declare idhinhanh int;
	begin
		idhinhanh := (select tbl_hinhanh.id
						from tbl_hinhanh
						where lower(tbl_hinhanh.duong_dan) = lower(p_duongdan));
		if idhinhanh is null then
			idhinhanh := -1;
		end if;
		return idhinhanh;
	end
$$ language plpgsql;
--Hàm cho phép thêm hình ảnh khi biết đường dẫn
create or replace function func_them_hinhanh(p_duongdan text, p_hinhanhthunho text)
returns bool as $$
	begin
		if func_layid_hinhanh(p_duongdan) = -1 then
			insert into tbl_hinhanh(duong_dan, hinhanh_thunho) values(p_duongdan, p_hinhanhthunho);
			return true;
		end if;
		return false;
	end
$$ language plpgsql;
--Hàm xóa hình ảnh
create or replace function func_xoa_hinhanh(p_idhinhanh int)
returns void as $$
	begin
		delete from tbl_hinhanh where id = p_idhinhanh;
	end
$$ language plpgsql;