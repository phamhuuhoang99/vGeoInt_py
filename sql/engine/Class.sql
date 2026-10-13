-------------------------------------------------------------------------------------------------------------------------
-- LOAI
-------------------------------------------------------------------------------------------------------------------------

create table tbl_loaidoituong
(
	id serial primary key,
	ten text not null,
	id_nhom int,
	foreign key(id_nhom) references tbl_nhomdoituong(id)
		on delete cascade on update cascade,
	unique(ten, id_nhom)
);
--Hàm lấy id loại đối tượng khi biết tên loại và tên nhóm
create or replace function func_layid_loaidoituong(p_tenloai text, p_tennhom text)
returns int as $$
	declare idloai int;
	begin
		idloai := (select tbl_loaidoituong.id
						from tbl_loaidoituong
						where tbl_loaidoituong.id_nhom = func_layid_nhomdoituong(p_tennhom)
							and lower(tbl_loaidoituong.ten) = lower(p_tenloai)); 
		if idloai is null then
			idloai := -1;
		end if;
		return idloai;
	end
$$ language plpgsql;
--Hàm thêm loại đối tượng
create or replace function func_them_loaidoituong(p_tenloai text, p_idnhom int)
returns void as $$
	begin
		insert into tbl_loaidoituong(ten, id_nhom) values(p_tenloai, p_idnhom)
			on conflict (ten, id_nhom) do nothing;
	end
$$ language plpgsql;
--Hàm thêm mới loại đối tượng khi biết tên nhóm
create or replace function func_them_loaidoituong(p_tenloai text, p_tennhom text)
returns bool as $$
	begin
		if func_layid_loaidoituong(p_tenloai, p_tennhom) = -1 then
			perform func_them_loaidoituong(p_tenloai, func_layid_nhomdoituong(p_tennhom));
			return true;
		end if;
		return false;
	end
$$ language plpgsql;
--
select func_them_loaidoituong('Quân sự/Ném bom', 'Máy bay');
select func_them_loaidoituong('Quân sự/Cường kích', 'Máy bay');
select func_them_loaidoituong('Quân sự/Tiêm kích', 'Máy bay');
select func_them_loaidoituong('Quân sự/Trinh sát chụp ảnh', 'Máy bay');
select func_them_loaidoituong('Quân sự/Trinh sát điện tử', 'Máy bay');
select func_them_loaidoituong('Quân sự/Trinh sát khí tượng', 'Máy bay');
select func_them_loaidoituong('Quân sự/Vận tải', 'Máy bay');
select func_them_loaidoituong('Quân sự/Tiếp dầu', 'Máy bay');
select func_them_loaidoituong('Quân sự/Liên lạc', 'Máy bay');
select func_them_loaidoituong('Quân sự/Huấn luyện', 'Máy bay');
select func_them_loaidoituong('Quân sự/Cấp cứu', 'Máy bay');
select func_them_loaidoituong('Quân sự/Tuần tiễu', 'Máy bay');
select func_them_loaidoituong('Quân sự/Cảnh giới', 'Máy bay');
select func_them_loaidoituong('Quân sự/Chống ngầm', 'Máy bay');
select func_them_loaidoituong('Quân sự/Quan sát - Trinh sát', 'Máy bay');
select func_them_loaidoituong('Quân sự/Đa năng', 'Máy bay');
select func_them_loaidoituong('Quân sự/Lên thẳng', 'Máy bay');
select func_them_loaidoituong('Quân sự/Thí nghiệm', 'Máy bay');
------------
select func_them_loaidoituong('Dân sự/Hành khách', 'Máy bay');
select func_them_loaidoituong('Dân sự/Vận tải', 'Máy bay');
select func_them_loaidoituong('Dân sự/Bưu chính', 'Máy bay');
select func_them_loaidoituong('Dân sự/Nông nghiệp', 'Máy bay');
select func_them_loaidoituong('Dân sự/Huấn luyện', 'Máy bay');
select func_them_loaidoituong('Dân sự/Thể thao', 'Máy bay');

select func_them_loaidoituong('Quân sự/Kết hợp', 'Sân bay');
select func_them_loaidoituong('Quân sự/Huấn luyện', 'Sân bay');
select func_them_loaidoituong('Quân sự/Chuyên dụng', 'Sân bay');
select func_them_loaidoituong('Quân sự/Cơ bản', 'Sân bay');
select func_them_loaidoituong('Quân sự/Dã chiến', 'Sân bay');
select func_them_loaidoituong('Quân sự/Dự bị', 'Sân bay');
select func_them_loaidoituong('Quân sự/Bến đỗ', 'Sân bay');
select func_them_loaidoituong('Quân sự/Cơ động', 'Sân bay');
select func_them_loaidoituong('Quân sự/Phục kích', 'Sân bay');
select func_them_loaidoituong('Quân sự/Đảm bảo vật chất', 'Sân bay');
select func_them_loaidoituong('Quân sự/Dự trữ', 'Sân bay');

select func_them_loaidoituong('Quân sự/Khu trục', 'Tàu thuyền');
select func_them_loaidoituong('Quân sự/Nước tấn công', 'Tàu thuyền');
select func_them_loaidoituong('Quân sự/Ngầm', 'Tàu thuyền');
select func_them_loaidoituong('Quân sự/Phụ trợ', 'Tàu thuyền');
select func_them_loaidoituong('Quân sự/Sân bay', 'Tàu thuyền');
select func_them_loaidoituong('Quân sự/Sân bay trực thăng', 'Tàu thuyền');
select func_them_loaidoituong('Quân sự/Tấn công phá hủy', 'Tàu thuyền');
select func_them_loaidoituong('Quân sự/Thu thập thông tin', 'Tàu thuyền');
select func_them_loaidoituong('Quân sự/Tuần dương', 'Tàu thuyền');
select func_them_loaidoituong('Quân sự/Tuần tra', 'Tàu thuyền');

select func_them_loaidoituong('Công trình bảo vệ căn cứ', 'Căn cứ');
select func_them_loaidoituong('Công trình cầu cảng', 'Căn cứ');
select func_them_loaidoituong('Khu nhiên liệu', 'Căn cứ');
select func_them_loaidoituong('Khu kỹ thuật', 'Căn cứ');
select func_them_loaidoituong('Khu thông tin liên lạc', 'Căn cứ');
select func_them_loaidoituong('Nhà tham mưu', 'Căn cứ');
--
--Hàm lấy tất cả tên loại đối tượng khi biết id nhóm
create or replace function func_laytatca_loaidoituong(p_idnhomdoituong int)
returns table(id int, ten text) as $$
	begin
		return query
			select tbl_loaidoituong.id, tbl_loaidoituong.ten
			from tbl_loaidoituong
			where tbl_loaidoituong.id_nhom = p_idnhomdoituong;
	end
$$ language plpgsql;
--Hàm xóa loại đối tượng khi biết id loại
create or replace function func_xoa_loaidoituong(p_idloai int)
returns void as $$
	begin
		delete
			from tbl_loaidoituong
			where id = p_idloai;
	end
$$ language plpgsql;
--Hàm sửa loại đối tượng
create or replace function func_sua_loaidoituong(p_idloai int, p_tenloai text)
returns void as $$
	begin
		update tbl_loaidoituong set ten = p_tenloai where id = p_idloai;
	end
$$ language plpgsql;