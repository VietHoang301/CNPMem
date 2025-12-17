from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy import or_   # NEW
import requests
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

app = Flask(__name__)

# CẤU HÌNH FLASK & DATABASE
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "smartbus.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "change-this-secret"

db = SQLAlchemy(app)
OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")
OSRM_PROFILE = os.getenv("OSRM_PROFILE", "driving")  # driving/foot/bike tùy server
OSRM_TIMEOUT = float(os.getenv("OSRM_TIMEOUT", "8"))
OSRM_MAX_COORDS = int(os.getenv("OSRM_MAX_COORDS", "70"))  # tránh gửi quá nhiều điểm

# ==================== CÁC MODEL DỮ LIỆU ====================

class TaiKhoan(db.Model):
    __tablename__ = "tai_khoan"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    mat_khau_hash = db.Column(db.String(128), nullable=False)
    vai_tro = db.Column(db.String(20), default="KHACH")
    trangThai = db.Column(db.String(20), default="HOAT_DONG")


class KhachHang(db.Model):
    __tablename__ = "khach_hang"
    maKH = db.Column(db.Integer, primary_key=True)

    hoTen = db.Column(db.String(100))
    soDienThoai = db.Column(db.String(20))
    diaChi = db.Column(db.String(200))
    ngaySinh = db.Column(db.String(20))

    ngayDangKy = db.Column(db.String(20))
    soCCCD = db.Column(db.String(20))

    tai_khoan_id = db.Column(db.Integer, db.ForeignKey("tai_khoan.id"), nullable=False)
    tai_khoan = db.relationship("TaiKhoan", backref=db.backref("khach_hang", uselist=False))

    hoa_don = db.relationship("HoaDon", backref="khach_hang", lazy=True)
    the_tus = db.relationship("TheTu", backref="khach_hang", lazy=True)


class TuyenXe(db.Model):
    __tablename__ = "tuyen_xe"
    maTuyen = db.Column(db.Integer, primary_key=True)
    maHienThi = db.Column(db.String(20), unique=True, nullable=False)
    tenTuyen = db.Column(db.String(100))
    diemBatDau = db.Column(db.String(100))
    diemKetThuc = db.Column(db.String(100))
    giaVe = db.Column(db.String(50))             # ví dụ: "7.000đ/lượt"
    soChuyenMoiNgay = db.Column(db.Integer)      # số chuyến mỗi ngày
    thoiGianHoatDong = db.Column(db.String(100)) # ví dụ: "05:30 – 19:00"
    ghiChu = db.Column(db.Text)                  # tùy chọn, thông tin thêm

    chuyen_xes = db.relationship("ChuyenXe", backref="tuyen", lazy=True)
    tram_dungs = db.relationship(
        "TramDung",
        back_populates="tuyen",
        lazy=True,
        order_by="TramDung.thuTuTrenTuyen"
    )


class ChuyenXe(db.Model):
    __tablename__ = "chuyen_xe"
    maChuyen = db.Column(db.Integer, primary_key=True)
    tuyen_id = db.Column(db.Integer, db.ForeignKey("tuyen_xe.maTuyen"))
    ngayKhoiHanh = db.Column(db.String(20))
    gioKhoiHanh = db.Column(db.String(20))

    ve_xe = db.relationship("VeXe", backref="chuyen", lazy=True)


class HoaDon(db.Model):
    __tablename__ = "hoa_don"
    maHoaDon = db.Column(db.Integer, primary_key=True)
    khach_hang_id = db.Column(db.Integer, db.ForeignKey("khach_hang.maKH"))

    ngayLap = db.Column(db.DateTime, default=datetime.utcnow)
    tongTien = db.Column(db.Float, default=0)
    phuongThucThanhToan = db.Column(db.String(50), default="TIEN_MAT")
    trangThai = db.Column(db.String(20), default="DA_THANH_TOAN")

    ve_xe = db.relationship("VeXe", backref="hoa_don", lazy=True)


class VeXe(db.Model):
    __tablename__ = "ve_xe"
    maVe = db.Column(db.Integer, primary_key=True)
    hoa_don_id = db.Column(db.Integer, db.ForeignKey("hoa_don.maHoaDon"))
    chuyen_id = db.Column(db.Integer, db.ForeignKey("chuyen_xe.maChuyen"))
    soGhe = db.Column(db.String(10))
    giaVe = db.Column(db.Float)
    trangThai = db.Column(db.String(20), default="CON HIEU LUC")


class TheTu(db.Model):
    __tablename__ = "the_tu"
    maThe = db.Column(db.Integer, primary_key=True)
    khach_hang_id = db.Column(db.Integer, db.ForeignKey("khach_hang.maKH"))
    maSoThe = db.Column(db.String(50))
    ngayBatDau = db.Column(db.String(20))
    ngayHetHan = db.Column(db.String(20))
    trangThai = db.Column(db.String(20), default="CON HAN")


class TramDung(db.Model):
    __tablename__ = "tram_dung"

    maTram = db.Column(db.Integer, primary_key=True)
    tenTram = db.Column(db.String(100), nullable=False)
    diaChi = db.Column(db.String(200))
    thuTuTrenTuyen = db.Column(db.Integer, nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    huong = db.Column(db.String(10))
    tuyen_id = db.Column(db.Integer, db.ForeignKey("tuyen_xe.maTuyen"), nullable=False)
    tuyen = db.relationship("TuyenXe", back_populates="tram_dungs")


# ==================== KHỞI TẠO DB & ADMIN ====================

with app.app_context():
    db.create_all()

    if not TaiKhoan.query.filter_by(vai_tro="ADMIN").first():
        admin = TaiKhoan(
            email="admin@smartbus.local",
            mat_khau_hash=generate_password_hash("admin123"),
            vai_tro="ADMIN"
        )
        db.session.add(admin)
        db.session.commit()


# ==================== HÀM TIỆN ÍCH ====================

def current_user():
    uid = session.get("user_id")
    if uid is None:
        return None
    return db.session.get(TaiKhoan, uid)

def build_stops_geo(tram_dungs, route_code=None):
    return [
        {
            "id": s.maTram,
            "name": s.tenTram,
            "address": s.diaChi,
            "lat": float(s.lat) if s.lat is not None else None,
            "lng": float(s.lng) if s.lng is not None else None,
            "order": s.thuTuTrenTuyen,
            "dir": (s.huong or "").upper() if hasattr(s, "huong") else None,
            "direction": (s.huong or "").upper() if hasattr(s, "huong") else None,
            "route_code": route_code or (s.tuyen.maHienThi if s.tuyen else None),
        }
        for s in tram_dungs
    ]


def _query_stops_by_direction(tuyen, dir_):
    dir_clean = (dir_ or "DI").upper()
    if dir_clean not in ("DI", "VE"):
        dir_clean = "DI"

    q = TramDung.query.filter(TramDung.tuyen_id == tuyen.maTuyen)

    # Backward compatible:
    # - DI: lấy huong=DI hoặc NULL (phòng trường hợp dữ liệu cũ chưa set huong)
    # - VE: lấy huong=VE
    if dir_clean == "DI":
        q = q.filter(or_(TramDung.huong == "DI", TramDung.huong.is_(None)))
    else:
        q = q.filter(TramDung.huong == "VE")

    return q.order_by(TramDung.thuTuTrenTuyen.asc(), TramDung.maTram.asc())


def stop_stats_for_direction(tuyen, dir_):
    stops = _query_stops_by_direction(tuyen, dir_).all()
    total = len(stops)
    with_geo = sum(1 for s in stops if s.lat is not None and s.lng is not None)
    percent = round((with_geo * 100.0) / total, 1) if total else 0.0

    return {
        "direction": dir_,
        "stops": total,
        "with_geo": with_geo,
        "percent_with_geo": percent,
        "has_enough_shape": total >= 2 and with_geo >= 2,
    }


def build_route_summary(tuyen):
    dir_stats = {d: stop_stats_for_direction(tuyen, d) for d in ("DI", "VE")}
    total_stops = sum(s["stops"] for s in dir_stats.values())
    total_geo = sum(s["with_geo"] for s in dir_stats.values())
    percent = round((total_geo * 100.0) / total_stops, 1) if total_stops else 0.0

    geometry_ok = all((s["has_enough_shape"] or s["stops"] == 0) for s in dir_stats.values())
    status = "Đủ" if (total_stops > 0 and geometry_ok and percent >= 80.0) else "Thiếu"

    return {
        "route_id": tuyen.maTuyen,
        "route_code": tuyen.maHienThi,
        "route_name": tuyen.tenTuyen,
        "start": tuyen.diemBatDau,
        "end": tuyen.diemKetThuc,
        "directions": dir_stats,
        "totals": {
            "stops": total_stops,
            "with_geo": total_geo,
            "percent_with_geo": percent,
        },
        "data_status": status,
    }


@app.context_processor
def inject_user():
    return dict(user=current_user())


# ==================== TRANG CHÍNH ====================

@app.route("/")
def home():
    # Home: landing nhưng có số liệu + vài tuyến nổi bật cho cảm giác "hệ thống thật"
    stats = {
        "routes": TuyenXe.query.count(),
        "stops": TramDung.query.count(),
        "trips": ChuyenXe.query.count(),
        "tickets": VeXe.query.count(),
    }

    featured_routes = (
        TuyenXe.query
        .order_by(TuyenXe.maTuyen.asc())
        .limit(6)
        .all()
    )

    user = current_user()
    return render_template("home.html", stats=stats, featured_routes=featured_routes, user=user)


# ==================== ĐĂNG KÝ / ĐĂNG NHẬP ====================

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("home"))

    if request.method == "POST":
        full_name = request.form.get("full_name")
        email = request.form.get("email")
        password = request.form.get("password")

        if not email or not password:
            flash("Email và mật khẩu không được để trống.")
            return redirect(url_for("register"))

        existed = TaiKhoan.query.filter_by(email=email).first()
        if existed:
            flash("Email này đã được sử dụng.")
            return redirect(url_for("register"))

        tk = TaiKhoan(
            email=email,
            mat_khau_hash=generate_password_hash(password),
            vai_tro="KHACH"
        )
        db.session.add(tk)
        db.session.flush()

        kh = KhachHang(
            hoTen=full_name,
            tai_khoan_id=tk.id,
            ngayDangKy=datetime.utcnow().strftime("%Y-%m-%d")
        )
        db.session.add(kh)
        db.session.commit()

        flash("Đăng ký thành công, hãy đăng nhập.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("home"))

    # lấy next từ query hoặc từ hidden input (POST)
    next_url = request.form.get("next") or request.args.get("next")

    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        tk = TaiKhoan.query.filter_by(email=email).first()
        if tk and check_password_hash(tk.mat_khau_hash, password):
            session["user_id"] = tk.id
            session["user_role"] = tk.vai_tro
            flash("Đăng nhập thành công.")

            # chống open-redirect: chỉ cho phép đường dẫn nội bộ
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)

            return redirect(url_for("home"))
        else:
            flash("Sai email hoặc mật khẩu.")

    return render_template("login.html", next_url=next_url)



@app.route("/logout")
def logout():
    session.clear()
    flash("Bạn đã đăng xuất.")
    return redirect(url_for("home"))


# ==================== PUBLIC ====================

@app.route("/routes")
def routes():
    # /routes là dashboard thao tác
    danh_sach_tuyen = TuyenXe.query.order_by(TuyenXe.maTuyen).all()
    initial_route_id = danh_sach_tuyen[0].maTuyen if danh_sach_tuyen else None
    return render_template(
        "routes.html",
        routes=danh_sach_tuyen,
        initial_route_id=initial_route_id,
    )

@app.route("/routes/<int:tuyen_id>")
def route_detail(tuyen_id):
    tuyen = TuyenXe.query.get_or_404(tuyen_id)
    trips = ChuyenXe.query.filter_by(tuyen_id=tuyen_id).all()
    return render_template(
        "route_detail.html",
        tuyen=tuyen,
        trips=trips,
    )


@app.route("/trips/<int:trip_id>")
def trip_detail(trip_id):
    user = current_user()
    trip = ChuyenXe.query.get_or_404(trip_id)
    tuyen = trip.tuyen  # quan hệ backref từ TuyenXe -> ChuyenXe

    # nếu URL có ?mode=admin thì hiểu là xem từ trang admin
    is_admin_mode = request.args.get("mode") == "admin"

    # lấy trạm của tuyến để hiển thị lộ trình + map
    danh_sach_tram = (
        TramDung.query
        .filter_by(tuyen_id=trip.tuyen_id)
        .order_by(TramDung.thuTuTrenTuyen)
        .all()
    )
    stops_geo = build_stops_geo(danh_sach_tram)

    return render_template(
        "trip_detail.html",
        trip=trip,
        tuyen=tuyen,
        stops=danh_sach_tram,
        stops_geo=stops_geo,
        is_admin_mode=is_admin_mode,
        user=user,
    )



@app.route("/trips/<int:trip_id>/book", methods=["GET", "POST"])
def booking(trip_id):
    user = current_user()
    if not user:
        flash("Bạn phải đăng nhập để đặt vé.")
        return redirect(url_for("login", next=request.path))

    trip = ChuyenXe.query.get_or_404(trip_id)
    tuyen = trip.tuyen

    seat_capacity = 40
    gia_mac_dinh = 50000
    booked_seats = {ve.soGhe for ve in trip.ve_xe if ve.trangThai != "DA_HUY"}

    if request.method == "POST":
        raw_seats = request.form.get("soGhe", "").strip()
        gia_ve = float(request.form.get("giaVe") or gia_mac_dinh)

        if not raw_seats:
            flash("Bạn phải chọn ít nhất một ghế.")
            return redirect(url_for("booking", trip_id=trip_id))

        seats = [s.strip() for s in raw_seats.split(",") if s.strip()]
        seats = sorted(set(seats))

        already = [s for s in seats if s in booked_seats]
        if already:
            flash("Các ghế đã có người đặt: " + ", ".join(already))
            return redirect(url_for("booking", trip_id=trip_id))

        kh = user.khach_hang
        if not kh:
            flash("Tài khoản của bạn chưa gắn với thông tin khách hàng.")
            return redirect(url_for("home"))

        tong_tien = gia_ve * len(seats)

        hoa_don = HoaDon(khach_hang=kh, tongTien=tong_tien)
        db.session.add(hoa_don)
        db.session.flush()

        for seat in seats:
            ve = VeXe(
                hoa_don=hoa_don,
                chuyen=trip,
                soGhe=seat,
                giaVe=gia_ve,
            )
            db.session.add(ve)

        db.session.commit()
        flash(f"Đặt {len(seats)} vé thành công! Mã hóa đơn: {hoa_don.maHoaDon}")
        return redirect(url_for("tickets"))

    return render_template(
        "booking.html",
        trip=trip,
        tuyen=tuyen,
        seat_capacity=seat_capacity,
        booked_seats=booked_seats,
        gia_mac_dinh=gia_mac_dinh,
        user=user,
    )


@app.route("/tickets")
def tickets():
    user = current_user()
    if not user:
        flash("Bạn cần đăng nhập để xem vé đã đặt.")
        return redirect(url_for("login"))

    khach = KhachHang.query.filter_by(tai_khoan_id=user.id).first()
    if not khach:
        flash("Không tìm thấy thông tin khách hàng.")
        return redirect(url_for("home"))

    tickets = (
        VeXe.query
        .join(HoaDon, VeXe.hoa_don_id == HoaDon.maHoaDon)
        .join(ChuyenXe, VeXe.chuyen_id == ChuyenXe.maChuyen)
        .join(TuyenXe, ChuyenXe.tuyen_id == TuyenXe.maTuyen)
        .filter(HoaDon.khach_hang_id == khach.maKH)
        .order_by(VeXe.maVe.desc())
        .all()
    )

    return render_template("tickets.html", tickets=tickets)


@app.route("/tickets/<int:ve_id>/cancel", methods=["POST"])
def cancel_ticket(ve_id):
    user = current_user()
    if not user:
        flash("Bạn cần đăng nhập để hủy vé.")
        return redirect(url_for("login"))

    khach = KhachHang.query.filter_by(tai_khoan_id=user.id).first()
    if not khach:
        flash("Không tìm thấy thông tin khách hàng.")
        return redirect(url_for("home"))

    ve = VeXe.query.get_or_404(ve_id)

    if not ve.hoa_don or ve.hoa_don.khach_hang_id != khach.maKH:
        flash("Bạn không có quyền hủy vé này.")
        return redirect(url_for("tickets"))

    if ve.trangThai == "DA_HUY":
        flash(f"Vé #{ve.maVe} đã được hủy trước đó.")
    else:
        ve.trangThai = "DA_HUY"
        db.session.commit()
        flash(f"Đã hủy vé #{ve.maVe} thành công.")

    return redirect(url_for("tickets"))


@app.route("/card-register")
def card_register():
    return render_template("card_register.html")


# ==================== ADMIN ====================

@app.route("/admin/routes", methods=["GET", "POST"])
def admin_routes():
    user = current_user()
    if not user or user.vai_tro != "ADMIN":
        flash("Bạn không có quyền truy cập!")
        return redirect(url_for("home"))

    # LOAD tuyến đang sửa (nếu có)
    edit_route = None
    edit_id = request.args.get("edit")
    if edit_id:
        edit_route = TuyenXe.query.get(int(edit_id))

    if request.method == "POST":
        ma_tuyen_id = (request.form.get("maTuyen") or "").strip()  # hidden
        ma_tuyen_display = (request.form.get("maHienThi") or "").strip()
        ten_tuyen = (request.form.get("tenTuyen") or "").strip()
        diem_bd = (request.form.get("diemBatDau") or "").strip()
        diem_kt = (request.form.get("diemKetThuc") or "").strip()

        if not ma_tuyen_display or not ten_tuyen:
            flash("Mã tuyến và tên tuyến không được để trống!")
            return redirect(url_for("admin_routes"))

        # Nếu đang sửa theo ID
        if ma_tuyen_id:
            tuyen = TuyenXe.query.get(int(ma_tuyen_id))
            if not tuyen:
                flash("Không tìm thấy tuyến để cập nhật.")
                return redirect(url_for("admin_routes"))

            # check trùng maHienThi với tuyến khác
            other = TuyenXe.query.filter_by(maHienThi=ma_tuyen_display).first()
            if other and other.maTuyen != tuyen.maTuyen:
                flash("Mã hiển thị bị trùng với tuyến khác.")
                return redirect(url_for("admin_routes", edit=tuyen.maTuyen))

            tuyen.maHienThi = ma_tuyen_display
            tuyen.tenTuyen = ten_tuyen
            tuyen.diemBatDau = diem_bd
            tuyen.diemKetThuc = diem_kt
            db.session.commit()
            flash("Đã cập nhật tuyến thành công!")
            return redirect(url_for("admin_routes"))

        # Nếu không có ID: tạo mới hoặc update theo maHienThi
        tuyen = TuyenXe.query.filter_by(maHienThi=ma_tuyen_display).first()
        if tuyen:
            tuyen.tenTuyen = ten_tuyen
            tuyen.diemBatDau = diem_bd
            tuyen.diemKetThuc = diem_kt
            flash("Đã cập nhật tuyến cũ thành công!")
        else:
            tuyen = TuyenXe(
                maHienThi=ma_tuyen_display,
                tenTuyen=ten_tuyen,
                diemBatDau=diem_bd,
                diemKetThuc=diem_kt,
            )
            db.session.add(tuyen)
            flash("Đã thêm tuyến mới thành công!")

        db.session.commit()
        return redirect(url_for("admin_routes"))

    danh_sach_tuyen = TuyenXe.query.order_by(TuyenXe.maTuyen).all()
    return render_template("admin_routes.html", routes=danh_sach_tuyen, edit_route=edit_route)


@app.route("/admin/routes/<int:tuyen_id>/stops", methods=["GET", "POST"])
def admin_route_stops(tuyen_id):
    user = current_user()
    if not user or user.vai_tro != "ADMIN":
        flash("Bạn không có quyền truy cập!")
        return redirect(url_for("home"))

    tuyen = TuyenXe.query.get_or_404(tuyen_id)

    # LOAD trạm đang sửa
    edit_stop = None
    edit_id = request.args.get("edit")
    if edit_id:
        edit_stop = TramDung.query.get(int(edit_id))
        if not edit_stop or edit_stop.tuyen_id != tuyen_id:
            edit_stop = None

    if request.method == "POST":
        ma_tram = request.form.get("maTram")
        ten_tram = (request.form.get("tenTram") or "").strip()
        dia_chi = (request.form.get("diaChi") or "").strip()
        thu_tu = request.form.get("thuTuTrenTuyen")
        lat = request.form.get("lat")
        lng = request.form.get("lng")

        # NEW: hướng DI/VE
        huong = (request.form.get("huong") or "DI").strip().upper()
        if huong not in ("DI", "VE"):
            flash("Hướng phải là DI hoặc VE.")
            return redirect(url_for("admin_route_stops", tuyen_id=tuyen_id))

        if not ten_tram or not lat or not lng or not thu_tu:
            flash("Vui lòng nhập đầy đủ tên trạm, vị trí và thứ tự.")
            return redirect(url_for("admin_route_stops", tuyen_id=tuyen_id))

        if ma_tram:
            tram = TramDung.query.get(int(ma_tram))
            if tram and tram.tuyen_id == tuyen_id:
                tram.tenTram = ten_tram
                tram.diaChi = dia_chi
                tram.thuTuTrenTuyen = int(thu_tu)
                tram.lat = float(lat)
                tram.lng = float(lng)
                tram.huong = huong  # NEW
                db.session.commit()
                flash("Đã cập nhật trạm dừng.")
            else:
                flash("Không tìm thấy trạm để cập nhật.")
        else:
            tram = TramDung(
                tenTram=ten_tram,
                diaChi=dia_chi,
                thuTuTrenTuyen=int(thu_tu),
                lat=float(lat),
                lng=float(lng),
                huong=huong,  # NEW
                tuyen_id=tuyen_id,
            )
            db.session.add(tram)
            db.session.commit()
            flash("Đã thêm trạm dừng mới.")

        return redirect(url_for("admin_route_stops", tuyen_id=tuyen_id))

    # NEW: sort theo huong rồi theo thuTu
    danh_sach_tram = (
        TramDung.query
        .filter_by(tuyen_id=tuyen_id)
        .order_by(TramDung.huong, TramDung.thuTuTrenTuyen)
        .all()
    )

    stops_geo = build_stops_geo(danh_sach_tram)

    return render_template(
        "admin_stops.html",
        tuyen=tuyen,
        stops=danh_sach_tram,
        stops_geo=stops_geo,
        edit_stop=edit_stop,
    )



@app.route("/admin/routes/<int:tuyen_id>/stops/<int:tram_id>/delete", methods=["POST"])
def admin_delete_stop(tuyen_id, tram_id):
    user = current_user()
    if not user or user.vai_tro != "ADMIN":
        flash("Bạn không có quyền truy cập!")
        return redirect(url_for("home"))

    tram = TramDung.query.get_or_404(tram_id)
    if tram.tuyen_id != tuyen_id:
        flash("Trạm không thuộc tuyến này.")
        return redirect(url_for("admin_route_stops", tuyen_id=tuyen_id))

    db.session.delete(tram)
    db.session.commit()
    flash("Đã xóa trạm dừng.")

    return redirect(url_for("admin_route_stops", tuyen_id=tuyen_id))


@app.route("/admin/routes/<int:tuyen_id>/trips", methods=["GET", "POST"])
def admin_route_trips(tuyen_id):
    user = current_user()
    if not user or user.vai_tro != "ADMIN":
        flash("Bạn không có quyền truy cập trang quản trị.")
        return redirect(url_for("home"))

    tuyen = TuyenXe.query.get_or_404(tuyen_id)

    # LOAD chuyến đang sửa
    edit_trip = None
    edit_id = request.args.get("edit")
    if edit_id:
        edit_trip = ChuyenXe.query.get(int(edit_id))
        if not edit_trip or edit_trip.tuyen_id != tuyen.maTuyen:
            edit_trip = None

    if request.method == "POST":
        action = request.form.get("action", "add_trip")

        if action == "add_trip":
            ngay = request.form.get("ngayKhoiHanh")
            gio = request.form.get("gioKhoiHanh")

            if not ngay or not gio:
                flash("Ngày và giờ khởi hành không được để trống.")
            else:
                trip = ChuyenXe(
                    tuyen_id=tuyen.maTuyen,
                    ngayKhoiHanh=ngay,
                    gioKhoiHanh=gio,
                )
                db.session.add(trip)
                db.session.commit()
                flash("Đã thêm chuyến mới.")

        elif action == "edit_trip":
            trip_id = request.form.get("trip_id")
            ngay = request.form.get("ngayKhoiHanh")
            gio = request.form.get("gioKhoiHanh")

            if not trip_id:
                flash("Thiếu trip_id.")
            else:
                trip = ChuyenXe.query.get(int(trip_id))
                if not trip or trip.tuyen_id != tuyen.maTuyen:
                    flash("Chuyến không hợp lệ.")
                elif trip.ve_xe:
                    flash("Không thể sửa chuyến vì đã có vé được đặt.")
                else:
                    trip.ngayKhoiHanh = ngay
                    trip.gioKhoiHanh = gio
                    db.session.commit()
                    flash("Đã cập nhật chuyến.")

        return redirect(url_for("admin_route_trips", tuyen_id=tuyen_id))

    danh_sach_chuyen = (
        ChuyenXe.query
        .filter_by(tuyen_id=tuyen.maTuyen)
        .order_by(ChuyenXe.maChuyen)
        .all()
    )
    danh_sach_tram = (
        TramDung.query
        .filter_by(tuyen_id=tuyen.maTuyen)
        .order_by(TramDung.thuTuTrenTuyen)
        .all()
    )
    stops_geo = build_stops_geo(danh_sach_tram)

    return render_template(
        "admin_trips.html",
        tuyen=tuyen,
        trips=danh_sach_chuyen,
        stops=danh_sach_tram,
        stops_geo=stops_geo,
        edit_trip=edit_trip,
    )


@app.route("/admin/routes/<int:tuyen_id>/delete", methods=["POST"])
def delete_route(tuyen_id):
    user = current_user()
    if not user or user.vai_tro != "ADMIN":
        flash("Bạn không có quyền truy cập!")
        return redirect(url_for("home"))

    tuyen = TuyenXe.query.get_or_404(tuyen_id)

    if tuyen.chuyen_xes or tuyen.tram_dungs:
        flash("Không thể xóa tuyến vì vẫn còn chuyến xe hoặc trạm dừng. Hãy xóa hết trước.")
        return redirect(url_for("admin_routes"))

    db.session.delete(tuyen)
    db.session.commit()
    flash(f"Đã xóa tuyến {tuyen.maHienThi}.")
    return redirect(url_for("admin_routes"))


@app.route("/admin/trips/<int:trip_id>/delete", methods=["POST"])
def delete_trip(trip_id):
    user = current_user()
    if not user or user.vai_tro != "ADMIN":
        flash("Bạn không có quyền truy cập!")
        return redirect(url_for("home"))

    trip = ChuyenXe.query.get_or_404(trip_id)
    tuyen_id = trip.tuyen_id

    if trip.ve_xe:
        flash("Không thể xóa chuyến vì đã có vé được đặt.")
        return redirect(url_for("admin_route_trips", tuyen_id=tuyen_id))

    db.session.delete(trip)
    db.session.commit()
    flash(f"Đã xóa chuyến #{trip.maChuyen}.")
    return redirect(url_for("admin_route_trips", tuyen_id=tuyen_id))

@app.route("/api/osrm/route", methods=["POST"])
def api_osrm_route():
    """
    Input JSON: { "coords": [[lat, lng], [lat, lng], ...] }  (>=2 điểm)
    Output: { ok, distance_m, duration_s, geometry }
    geometry: GeoJSON LineString (coordinates = [lng, lat])
    """
    data = request.get_json(silent=True) or {}
    coords = data.get("coords")

    if not isinstance(coords, list) or len(coords) < 2:
        return jsonify({"ok": False, "error": "coords phải là list và có ít nhất 2 điểm"}), 400

    if len(coords) > OSRM_MAX_COORDS:
        return jsonify({"ok": False, "error": f"Quá nhiều điểm ({len(coords)}). Giới hạn: {OSRM_MAX_COORDS}"}), 400

    points = []
    try:
        for item in coords:
            if not (isinstance(item, (list, tuple)) and len(item) == 2):
                return jsonify({"ok": False, "error": "Mỗi điểm phải là [lat, lng]"}), 400
            lat = float(item[0]); lng = float(item[1])
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                return jsonify({"ok": False, "error": f"Tọa độ không hợp lệ: {lat}, {lng}"}), 400
            points.append((lng, lat))  # OSRM: lon,lat
    except Exception:
        return jsonify({"ok": False, "error": "coords có giá trị không chuyển được sang số"}), 400

    coord_str = ";".join([f"{lng},{lat}" for (lng, lat) in points])
    url = f"{OSRM_BASE_URL}/route/v1/{OSRM_PROFILE}/{coord_str}"
    params = {"overview": "full", "geometries": "geojson", "steps": "false"}

    try:
        r = requests.get(url, params=params, timeout=OSRM_TIMEOUT, headers={"User-Agent": "smartbus-demo"})
        j = r.json() if r.content else {}
    except Exception as e:
        return jsonify({"ok": False, "error": "Gọi OSRM thất bại", "detail": str(e)}), 502

    if r.status_code != 200 or j.get("code") != "Ok" or not j.get("routes"):
        return jsonify({"ok": False, "error": "OSRM không trả route", "raw": j}), 502

    route = j["routes"][0]
    return jsonify({
        "ok": True,
        "distance_m": route.get("distance"),
        "duration_s": route.get("duration"),
        "geometry": route.get("geometry"),
    })


@app.route("/api/routes/<int:tuyen_id>/summary")
def api_route_summary(tuyen_id):
    tuyen = TuyenXe.query.get_or_404(tuyen_id)
    return jsonify(build_route_summary(tuyen))


@app.route("/api/routes/<int:tuyen_id>/stops_geo")
def api_route_stops_geo(tuyen_id):
    tuyen = TuyenXe.query.get_or_404(tuyen_id)

    dir_ = (request.args.get("dir") or "DI").strip().upper()
    stops = _query_stops_by_direction(tuyen, dir_).all()

    return jsonify(build_stops_geo(stops, route_code=tuyen.maHienThi))
# ==================== MAIN ====================

if __name__ == "__main__":
    app.run(debug=True)
