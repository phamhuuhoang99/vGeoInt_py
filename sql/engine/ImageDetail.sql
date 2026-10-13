-------------------------------------------------------------------------------------------------------------------------
-- CHI TIET HINH ANH
-------------------------------------------------------------------------------------------------------------------------
create table tbl_chitiet_hinhanh
(
	ido varchar(8),
	id_hinhanh int,
	foreign key(id_hinhanh) references tbl_hinhanh(id)
		on delete cascade on update cascade,
	primary key(ido, id_hinhanh)
);
--them
create or replace function func_them_chitiet_hinhanh(p_ido varchar(8), p_idhinhanh int)
returns void as $$
	begin
		insert into tbl_chitiet_hinhanh(ido, id_hinhanh) values(p_ido, p_idhinhanh)
		on conflict(ido, id_hinhanh) do nothing;
	end
$$ language plpgsql;
--xoa
create or replace function func_xoa_chitiet_hinhanh(p_ido varchar(8), p_idhinhanh int)
returns void as $$
	begin
		delete from tbl_chitiet_hinhanh where ido = p_ido and id_hinhanh = p_idhinhanh;
	end
$$ language plpgsql;
create or replace function func_xoa_chitiet_hinhanh(p_ido varchar(8), p_duongdan text)
returns void as $$
	begin
		perform func_xoa_chitiet_hinhanh(p_ido, func_layid_hinhanh(p_duongdan));
	end
$$ language plpgsql;

--lay danh sach hinh anh
create or replace function func_lay_dshinhanh(p_ido varchar(8))
returns table(id int, duong_dan text, hinhanh_thunho text) as $$
	begin
		return query
			select tbl_hinhanh.id, tbl_hinhanh.duong_dan, tbl_hinhanh.hinhanh_thunho
			from tbl_chitiet_hinhanh, tbl_hinhanh
			where ido = p_ido and tbl_chitiet_hinhanh.id_hinhanh = tbl_hinhanh.id;
	end
$$ language plpgsql;
