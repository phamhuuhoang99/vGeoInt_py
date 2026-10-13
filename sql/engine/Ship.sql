create table tbl_tauthuyen
(
	ido varchar(8) primary key,
	chieudai real,
	chieurong real,
	momnuoc real,
	taitrong real,
	dongco text,
	chanvit int,
	congsuat int,
	tocdo real,
	tamhoatdong real,
	thuythudoan int,
	nuocsohuu text
);
--
create or replace function func_them_tauthuyen(
	p_ido varchar(8),
	p_chieudai real,
	p_chieurong real,
	p_momnuoc real,
	p_taitrong real,
	p_dongco text,
	p_chanvit int,
	p_congsuat int,
	p_tocdo real,
	p_tamhoatdong real,
	p_thuythudoan int,
	p_nuocsohuu text)
returns void as $$
	begin
		insert into tbl_tauthuyen(
			ido,
			chieudai,
			chieurong,
			momnuoc,
			taitrong,
			dongco,
			chanvit,
			congsuat,
			tocdo,
			tamhoatdong,
			thuythudoan,
			nuocsohuu) 
		values(
			p_ido,
			p_chieudai,
			p_chieurong,
			p_momnuoc,
			p_taitrong,
			p_dongco,
			p_chanvit,
			p_congsuat,
			p_tocdo,
			p_tamhoatdong,
			p_thuythudoan,
			p_nuocsohuu)
		on conflict (ido) do update set
			chieudai = p_chieudai,
			chieurong = p_chieurong,
			momnuoc = p_momnuoc,
			taitrong = p_taitrong,
			dongco = p_dongco,
			chanvit = p_chanvit,
			congsuat = p_congsuat,
			tocdo = p_tocdo,
			tamhoatdong = p_tamhoatdong,
			thuythudoan = p_thuythudoan,
			nuocsohuu = p_nuocsohuu;			
	end
$$ language plpgsql;

create or replace function func_lay_tauthuyen(p_ido varchar(8))
returns table(
	chieudai real,
	chieurong real,
	momnuoc real,
	taitrong real,
	dongco text,
	chanvit int,
	congsuat int,
	tocdo real,
	tamhoatdong real,
	thuythudoan int,
	nuocsohuu text)
as $$
	begin
		return query
			select
				tbl_tauthuyen.chieudai,
				tbl_tauthuyen.chieurong,
				tbl_tauthuyen.momnuoc,
				tbl_tauthuyen.taitrong,
				tbl_tauthuyen.dongco,
				tbl_tauthuyen.chanvit,
				tbl_tauthuyen.congsuat,
				tbl_tauthuyen.tocdo,
				tbl_tauthuyen.tamhoatdong,
				tbl_tauthuyen.thuythudoan,
				tbl_tauthuyen.nuocsohuu
			from tbl_tauthuyen
			where tbl_tauthuyen.ido = p_ido;
	end
$$ language plpgsql;