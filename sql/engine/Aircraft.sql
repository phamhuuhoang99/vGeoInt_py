create table tbl_maybay
(
	ido varchar(8) primary key,
	chieudaithan real,
	saicanh real,
	chieucao real,
	dongco text,
	vmax real,
	hmax real,
	tambay_max real,
	bankinh_hoatdong real,
	nuoc_sanxuat text
);
--Hàm thêm thuộc tính máy bay
create or replace function func_them_maybay(
	p_ido varchar(8),
	p_chieudaithan real,
	p_saicanh real,
	p_chieucao real,
	p_dongco text,
	p_vmax real,
	p_hmax real,
	p_tambaymax real,
	p_bankinhhoatdong real,
	p_nuocsanxuat text)
returns void as $$
	begin
		insert into tbl_maybay(
				ido,
				chieudaithan,
				saicanh,
				chieucao,
				dongco,
				vmax,
				hmax,
				tambay_max,
				bankinh_hoatdong,
				nuoc_sanxuat)
			values(
				p_ido,
				p_chieudaithan,
				p_saicanh,
				p_chieucao,
				p_dongco,
				p_vmax,
				p_hmax,
				p_tambaymax,
				p_bankinhhoatdong,
				p_nuocsanxuat)
			on conflict (ido) do update set
				chieudaithan = excluded.chieudaithan,
				saicanh = excluded.saicanh,
				chieucao = excluded.chieucao,
				dongco = excluded.dongco,
				vmax = excluded.vmax,
				hmax = excluded.hmax,
				tambay_max = excluded.tambay_max,
				bankinh_hoatdong = excluded.bankinh_hoatdong,
				nuoc_sanxuat = excluded.nuoc_sanxuat;
	end
$$ language plpgsql;

--Hàm lấy thuộc tính máy bay khi biết id đối tượng
create or replace function func_lay_maybay(p_ido varchar(8))
returns table(
	chieudaithan real,
	saicanh real,
	chieucao real,
	dongco text,
	vmax real,
	hmax real,
	tambay_max real,
	bankinh_hoatdong real,
	nuoc_sanxuat text)
as $$
	begin
		return query
			select
				tbl_maybay.chieudaithan,
				tbl_maybay.saicanh,
				tbl_maybay.chieucao,
				tbl_maybay.dongco,
				tbl_maybay.vmax,
				tbl_maybay.hmax,
				tbl_maybay.tambay_max,
				tbl_maybay.bankinh_hoatdong,
				tbl_maybay.nuoc_sanxuat
			from tbl_maybay
			where tbl_maybay.ido = p_ido;
	end
$$ language plpgsql;