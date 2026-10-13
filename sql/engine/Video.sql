-------------------------------------------------------------------------------------------------------------------------
-- VIDEO
-------------------------------------------------------------------------------------------------------------------------
create table tbl_video
(
	id serial primary key,
	duong_dan text unique not null,
	hinhanh_thunho text
);
--Tạo hàm lấy id video khi biết đường dẫn
create or replace function func_layid_video(p_duongdan text)
returns int as $$
	declare idvideo int;
	begin
		idvideo := (select tbl_video.id
						from tbl_video
						where lower(tbl_video.duong_dan) = lower(p_duongdan));
		if idvideo is null then
			idvideo := -1;
		end if;
		return idvideo;
	end
$$ language plpgsql;
--Hàm thêm video khi biết đường dẫn
create or replace function func_them_video(p_duongdan text, p_hinhanhthunho text)
returns bool as $$
	begin
		if func_layid_video(p_duongdan) = -1 then
			insert into tbl_video(duong_dan, hinhanh_thunho) values(p_duongdan, p_hinhanhthunho);
			return true;
		end if;
		return false;
	end
$$ language plpgsql;
--Hàm xóa video
create or replace function func_xoa_video(p_idvideo int)
returns void as $$
	begin
		delete from tbl_video where id = p_idvideo;
	end
$$ language plpgsql;