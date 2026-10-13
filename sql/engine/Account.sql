-------------------------------------------------------------------------------------------------------------------------
-- TAI KHOAN
-------------------------------------------------------------------------------------------------------------------------
create table if not exists tbl_taikhoan
(
	id serial primary key,
	tendangnhap varchar(32) unique not null,
	matkhau varchar(32) not null,
	quyen int not null
);

--Hàm lấy id khi biết tên đăng nhập
create or replace function func_layid_taikhoan(varchar(32))
returns int as $$
	declare idtaikhoan int;
	begin
		idtaikhoan := (select id from tbl_taikhoan where lower(tendangnhap) = lower($1) );
		if idtaikhoan is null then
			idtaikhoan := -1;
		end if;
	return idtaikhoan;
	end
$$ language plpgsql;

--Lấy danh sách tài khoản
create or replace function func_laytatca_taikhoan()
returns table(tendangnhap varchar(32), quyen int) as $$
	begin
		return query
			select tbl_taikhoan.tendangnhap, tbl_taikhoan.quyen
			from tbl_taikhoan;
	end
$$ language plpgsql;

-- Cập nhật mật khẩu mới
create or replace function func_doimatkhau_taikhoan(varchar(32), varchar(32))
returns bool as $$
	declare idtaikhoan int;
	begin
		idtaikhoan := (select func_layid_taikhoan($1));
		if idtaikhoan = -1 then
			return false;
		end if;
		update tbl_taikhoan set matkhau=$2 where id=idtaikhoan;
		return true;
	end
$$ language plpgsql;

-- Cập nhật quyền mới
create or replace function func_doiquyen_taikhoan(varchar(32), int)
returns bool as $$
	declare idtaikhoan int;
	begin
		idtaikhoan := (select func_layid_taikhoan($1));
		if idtaikhoan = -1 then
			return false;
		end if;
		update tbl_taikhoan set quyen=$2 where id=idtaikhoan;
		return true;
	end
$$ language plpgsql;

----Hàm thêm tài khoản
create or replace function func_them_taikhoan(varchar(32), varchar(32), int)
returns bool as $$
	declare idtaikhoan int;
	begin
		idtaikhoan := (select func_layid_taikhoan($1));
		if idtaikhoan <> -1 then
			return false;
		end if;
		insert into tbl_taikhoan(tendangnhap, matkhau, quyen) values($1,$2,$3);
		return true;
	end
$$ language plpgsql;

-- Xóa tài khoản khi biết tên tài khoản
create or replace function func_xoa_taikhoan(varchar(32))
returns void as $$
	begin
		delete from tbl_taikhoan where tendangnhap=$1;
	end
$$ language plpgsql;

--Thêm tài khoản mặc định
select func_them_taikhoan('admin', '63ad7e2db3f548ed471b9b1b73fbcf43', 1);
select func_them_taikhoan('user',  '4297f44b13955235245b2497399d7a93', 2);

-- Kiểm tra tài khoản và mật khẩu, trả về quyền (1: admin, 2: User, -1: thất bại)
create or replace function func_kiemtra_dangnhap(varchar(32), varchar(32))
returns int as $$
	declare q int;
	begin
		q := (select quyen from tbl_taikhoan where tendangnhap=$1 and matkhau=$2);
		if q is null then
			return -1;
		end if;
		return q;
	end
$$ language plpgsql;