-------------------------------------------------------------------------------------------------------------------------
-- NHOM
-------------------------------------------------------------------------------------------------------------------------
create table tbl_nhomdoituong
(
	id serial primary key,
	ten text unique not null
);
--
create or replace function func_them_nhomdoituong(p_ten text)
returns void as $$
	begin
		insert into tbl_nhomdoituong(ten) values(p_ten)
		on conflict (ten) do nothing;
	end
$$ language plpgsql;
--
select func_them_nhomdoituong('Máy bay');
select func_them_nhomdoituong('Sân bay');
select func_them_nhomdoituong('Xe tăng');
select func_them_nhomdoituong('Trận địa tên lửa');
select func_them_nhomdoituong('Tàu thuyền');
select func_them_nhomdoituong('Căn cứ');
select func_them_nhomdoituong('Cảng quân sự');
select func_them_nhomdoituong('Kho quân sự');
select func_them_nhomdoituong('Khác');
--
--Hàm lấy id nhóm khi biết tên nhóm
create or replace function func_layid_nhomdoituong(p_tennhom text)
returns int as $$
	declare idnhom int;
	begin
		idnhom := (select tbl_nhomdoituong.id
					from tbl_nhomdoituong
					where lower(tbl_nhomdoituong.ten) = lower(p_tennhom));
		if idnhom is null then
			idnhom := -1;
		end if;
		return idnhom;
	end
$$ language plpgsql;
--Hàm lấy tên tất nhóm
create or replace function func_laytatca_nhomdoituong()
returns table(id int, ten text) as $$
	begin
		return query
			select tbl_nhomdoituong.id, tbl_nhomdoituong.ten
			from tbl_nhomdoituong;
	end
$$ language plpgsql;
--Hàm xóa nhóm
create or replace function func_xoa_nhomdoituong(p_idnhom int)
returns void as $$
	begin
		delete from tbl_nhomdoituong
			where id = p_idnhom;
	end
$$ language plpgsql;
--Hàm xóa nhóm
create or replace function func_xoa_nhomdoituong(p_tennhom text)
returns void as $$
	begin
		delete from tbl_nhomdoituong
			where lower(ten) = lower(p_tennhom);
	end
$$ language plpgsql;
--Hàm sửa tên nhóm
create or replace function func_sua_nhomdoituong(p_idnhom int, p_tennhom text)
returns void as $$
	begin
		update tbl_nhomdoituong set ten=p_tennhom where id = p_idnhom;
	end
$$ language plpgsql;