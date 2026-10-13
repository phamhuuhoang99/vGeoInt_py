create table tbl_trandiatenlua
(
	ido varchar(8) primary key,
	so_be int,
	so_xerada int,
	so_xechihuy int,
	duongkinh real,
	nuoc_sohuu text
);

--Hàm thêm thuộc tính máy bay
create or replace function func_them_trandiatenlua(
	p_ido varchar(8),
	p_sobe int,
	p_soxerada int,
	p_soxechihuy int,
	p_duongkinh real,
	p_nuocsanxuat text)
returns void as $$
	begin
		insert into tbl_trandiatenlua(
				ido,
				so_be,
				so_xerada,
				so_xechihuy,
				duongkinh,
				nuoc_sohuu)
			values(
				p_ido,
				p_sobe,
				p_soxerada,
				p_soxechihuy,
				p_duongkinh,
				p_nuocsanxuat)
			on conflict (ido) do update set
				so_be = excluded.so_be,
				so_xerada = excluded.so_xerada,
				so_xechihuy = excluded.so_xechihuy,
				duongkinh = excluded.duongkinh,
				nuoc_sohuu = excluded.nuoc_sohuu;
	end
$$ language plpgsql;

--Hàm lấy thuộc tính máy bay khi biết id đối tượng
create or replace function func_lay_trandiatenlua(p_ido varchar(8))
returns table(
	so_be int,
	so_xerada int,
	so_xechihuy int,
	duongkinh real,
	nuoc_sohuu text)
as $$
	begin
		return query
			select
				tbl_trandiatenlua.so_be,
				tbl_trandiatenlua.so_xerada,
				tbl_trandiatenlua.so_xechihuy,
				tbl_trandiatenlua.duongkinh,
				tbl_trandiatenlua.nuoc_sohuu
			from tbl_trandiatenlua
			where tbl_trandiatenlua.ido = p_ido;
	end
$$ language plpgsql;