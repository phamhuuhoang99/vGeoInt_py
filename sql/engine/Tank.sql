create table tbl_xetang
(
	ido varchar(8) primary key,
	chieudai real,
	chieurong real,
	taitrong real,
	nuoc_sohuu text
);
--Hàm thêm thuộc tính máy bay
create or replace function func_them_xetang(
	p_ido varchar(8),
	p_chieudai real,
	p_chieurong real,
	p_taitrong real,
	p_nuocsanxuat text)
returns void as $$
	begin
		insert into tbl_xetang(
				ido,
				chieudai,
				chieurong,
				taitrong,
				nuoc_sohuu)
			values(
				p_ido,
				p_chieudai,
				p_chieurong,
				p_taitrong,
				p_nuocsanxuat)
			on conflict (ido) do update set
				chieudai = excluded.chieudai,
				chieurong = excluded.chieurong,
				taitrong = excluded.taitrong,
				nuoc_sohuu = excluded.nuoc_sohuu;
	end
$$ language plpgsql;

--Hàm lấy thuộc tính máy bay khi biết id đối tượng
create or replace function func_lay_xetang(p_ido varchar(8))
returns table(
	chieudai real,
	chieurong real,
	taitrong real,
	nuoc_sohuu text)
as $$
	begin
		return query
			select
				tbl_xetang.chieudai,
				tbl_xetang.chieurong,
				tbl_xetang.taitrong,
				tbl_xetang.nuoc_sohuu
			from tbl_xetang
			where tbl_xetang.ido = p_ido;
	end
$$ language plpgsql;