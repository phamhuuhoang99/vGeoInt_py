-------------------------------------------------------------------------------------------------------------------------
-- KIEU
-------------------------------------------------------------------------------------------------------------------------

create table tbl_kieudoituong(
	id serial primary key,
	ten text not null,
	id_loai int,
	foreign key(id_loai) references tbl_loaidoituong(id)
		on delete cascade on update cascade,
	unique(ten, id_loai)
);
create or replace function func_layid_kieudoituong(p_tenkieu text, p_tenloai text, p_tennhom text)
returns int as $$
	declare idkieu int;
	begin
		idkieu := (select tbl_kieudoituong.id
					from tbl_kieudoituong
					where lower(tbl_kieudoituong.ten) = lower(p_tenkieu)
						and tbl_kieudoituong.id_loai = func_layid_loaidoituong(p_tenloai, p_tennhom));
		if idkieu is null then
			idkieu := -1;
		end if;
		return idkieu;
	end
$$ language plpgsql;
-- Hàm thêm kiểu đối tượng khi biết id loại
create or replace function func_them_kieudoituong(p_tenkieu text, p_idloai int)
returns void as $$
	begin 
		insert into tbl_kieudoituong(ten, id_loai) values(p_tenkieu, p_idloai)
			on conflict (ten, id_loai) do nothing;
	end
$$ language plpgsql;
-- Hàm thêm kiểu đối tượng khi biết tên loại và tên nhóm
create or replace function func_them_kieudoituong(p_tenkieu text, p_tenloai text, p_tennhom text)
returns bool as $$
	begin 
		if func_layid_kieudoituong(p_tenkieu, p_tenloai, p_tennhom) = -1 then
			perform func_them_kieudoituong(p_tenkieu, func_layid_loaidoituong(p_tenloai, p_tennhom));
			return true;
		end if;
		return false;
	end
$$ language plpgsql;

--
--Hàm lấy tên tất cả kiểu đối tượng khi biết id loại đối tượng
create or replace function func_laytatca_kieudoituong(p_idloai int)
returns table(id int, ten text) as $$
	begin
		return query
			select tbl_kieudoituong.id, tbl_kieudoituong.ten
			from tbl_kieudoituong
			where tbl_kieudoituong.id_loai = p_idloai;
	end
$$ language plpgsql;
--Hàm lấy id loại và id nhóm từ id kiểu
create or replace function func_layid_loainhom(p_idkieu int)
returns table(id_loai int, id_nhom int) as $$
	begin
		return query
			select tbl_loaidoituong.id, tbl_nhomdoituong.id
			from tbl_kieudoituong, tbl_loaidoituong, tbl_nhomdoituong
			where tbl_kieudoituong.id_loai = tbl_loaidoituong.id
				and tbl_loaidoituong.id_nhom = tbl_nhomdoituong.id
				and tbl_kieudoituong.id = p_idkieu;
	end
$$ language plpgsql;
--
create or replace function func_lay_tennhom_idt(p_idophanloai varchar(8))
returns text as $$
	declare
		rec record;
		code text;
		idn int;
	begin
		code := substring(p_idophanloai, 1, 3);
		idn := substring(p_idophanloai, 4);
		if code = 'TYP' then
			select into rec tbl_nhomdoituong.ten
			from tbl_kieudoituong, tbl_loaidoituong, tbl_nhomdoituong
			where tbl_kieudoituong.id_loai = tbl_loaidoituong.id
					and tbl_loaidoituong.id_nhom = tbl_nhomdoituong.id
					and tbl_kieudoituong.id = idn;
		else
			select into rec tbl_nhomdoituong.ten
			from tbl_nhomdoituong
			where tbl_nhomdoituong.id = idn;
		end if;
		return rec.ten;
	end
$$ language plpgsql;
--
create or replace function func_sua_kieudoituong(p_idkieu int, p_tenkieu text)
returns void as $$
	begin
		update tbl_kieudoituong set ten=p_tenkieu where id = p_idkieu;
	end
$$ language plpgsql;

--Hàm xóa kiểu dữ liệu
create or replace function func_xoa_kieudoituong(p_idkieu int)
returns void as $$
	begin
		delete from tbl_kieudoituong
			where tbl_kieudoituong.id = p_idkieu;
	end
$$ language plpgsql;