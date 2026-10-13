-------------------------------------------------------------------------------------------------------------------------
-- CHI TIET TAI LIEU
-------------------------------------------------------------------------------------------------------------------------
create table tbl_chitiet_tailieu
(
	ido varchar(8),
	id_tailieu int,
	foreign key(id_tailieu) references tbl_tailieu(id)
		on delete cascade on update cascade,
	primary key(ido, id_tailieu)
);
-- them
create or replace function func_them_chitiet_tailieu(p_ido varchar(8), p_idtailieu int)
returns void as $$
	begin
		insert into tbl_chitiet_tailieu(ido, id_tailieu) values(p_ido, p_idtailieu)
		on conflict(ido, id_tailieu) do nothing;
	end
$$ language plpgsql;
--xoa
create or replace function func_xoa_chitiet_tailieu(p_ido varchar(8), p_idtailieu int)
returns void as $$
	begin
		delete from tbl_chitiet_tailieu where ido = p_ido and id_tailieu = p_idtailieu;
	end
$$ language plpgsql;

create or replace function func_xoa_chitiet_tailieu(p_ido varchar(8), p_duongdan text)
returns void as $$
	begin
		perform func_xoa_chitiet_tailieu(p_ido, func_layid_tailieu(p_duongdan));
	end
$$ language plpgsql;

--lay ds tailieu
create or replace function func_lay_dstailieu(p_ido varchar(8))
returns table(id int, duong_dan text) as $$
	begin
		return query
			select tbl_tailieu.id, tbl_tailieu.duong_dan
			from tbl_chitiet_tailieu, tbl_tailieu
			where ido = p_ido and tbl_chitiet_tailieu.id_tailieu = tbl_tailieu.id;
	end
$$ language plpgsql;