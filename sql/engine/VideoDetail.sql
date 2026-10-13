-------------------------------------------------------------------------------------------------------------------------
-- CHI TIET VIDEO
-------------------------------------------------------------------------------------------------------------------------

create table tbl_chitiet_video
(
	ido varchar(8),
	id_video int,
	foreign key(id_video) references tbl_video(id)
		on delete cascade on update cascade,
	primary key(ido, id_video)
);
-- them
create or replace function func_them_chitiet_video(p_ido varchar(8), p_idvideo int)
returns void as $$
	begin
		insert into tbl_chitiet_video(ido, id_video) values(p_ido, p_idvideo)
		on conflict(ido, id_video) do nothing;
	end
$$ language plpgsql;
--xoa
create or replace function func_xoa_chitiet_video(p_ido varchar(8), p_idvideo int)
returns void as $$
	begin
		delete from tbl_chitiet_video where ido = p_ido and id_video = p_idvideo;
	end
$$ language plpgsql;
create or replace function func_xoa_chitiet_video(p_ido varchar(8), p_duongdan text)
returns void as $$
	begin
		perform func_xoa_chitiet_video(p_ido, func_layid_video(p_duongdan));
	end
$$ language plpgsql;
--lay ds video
create or replace function func_lay_dsvideo(p_ido varchar(8))
returns table(id int, duong_dan text, hinhanh_thunho text) as $$
	begin
		return query
			select tbl_video.id, tbl_video.duong_dan, tbl_video.hinhanh_thunho
			from tbl_chitiet_video, tbl_video
			where ido = p_ido and tbl_chitiet_video.id_video = tbl_video.id;
	end
$$ language plpgsql;