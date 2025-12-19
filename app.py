from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
import requests
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import hashlib
import math
import os
import re
import time

app = Flask(__name__)

# Cấu hình Flask & database (ưu tiên env để dễ deploy)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

db_url = os.getenv("DATABASE_URL") or os.getenv("SQLALCHEMY_DATABASE_URI")
if db_url and db_url.startswith("postgres://"):
    # SQLAlchemy dùng "postgresql://"
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url or ("sqlite:///" + os.path.join(BASE_DIR, "smartbus.db"))
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "08082004258046121011")

db = SQLAlchemy(app)
OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")
OSRM_PROFILE = os.getenv("OSRM_PROFILE", "driving")  # driving/foot/bike tùy server
OSRM_TIMEOUT = float(os.getenv("OSRM_TIMEOUT", "8"))
OSRM_MAX_COORDS = int(os.getenv("OSRM_MAX_COORDS", "70"))  # tránh gửi quá nhiều điểm
BUS_TRIP_CAPACITY = int(os.getenv("BUS_TRIP_CAPACITY", "80"))  # bus đô thị: không theo ghế
BUS_SCHEDULE_HORIZON_MIN = int(os.getenv("BUS_SCHEDULE_HORIZON_MIN", "360"))  # auto-generate N phút sắp tới
BUS_OSRM_DURATION_FACTOR = float(os.getenv("BUS_OSRM_DURATION_FACTOR", "1.25"))  # bus chậm hơn xe hơi (OSRM driving)
BUS_STOP_DWELL_SEC = int(os.getenv("BUS_STOP_DWELL_SEC", "15"))  # dừng đón/trả khách mỗi trạm (ước tính)
BUS_FALLBACK_SPEED_KMH = float(os.getenv("BUS_FALLBACK_SPEED_KMH", "22"))  # fallback nếu OSRM fail
STOP_OFFSET_CACHE_TTL_SEC = int(os.getenv("STOP_OFFSET_CACHE_TTL_SEC", "900"))
_STOP_OFFSET_CACHE = {}

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
    khoangCachKm = db.Column(db.Float)           # khoảng cách tuyến (km)
    tanSuatPhut = db.Column(db.Integer)          # tần suất (phút/chuyến)

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
    huong = db.Column(db.String(10), default="DI")  # DI/VE (bus đô thị)

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
    maSoVe = db.Column(db.String(50))  # mã vé/QR (không theo ghế)
    giaVe = db.Column(db.Float)
    trangThai = db.Column(db.String(20), default="CON HIEU LUC")
    thoiGianSuDung = db.Column(db.String(30))  # khi soát vé (demo)


class TheTu(db.Model):
    __tablename__ = "the_tu"
    maThe = db.Column(db.Integer, primary_key=True)
    khach_hang_id = db.Column(db.Integer, db.ForeignKey("khach_hang.maKH"))
    maSoThe = db.Column(db.String(50))
    loaiThe = db.Column(db.String(20))  # THANG/QUY/NAM
    giaTri = db.Column(db.Float)        # giá trị tham khảo
    ngayBatDau = db.Column(db.String(20))
    ngayHetHan = db.Column(db.String(20))
    trangThai = db.Column(db.String(20), default="CON HAN")
    nguoiDuyet = db.Column(db.String(120))
    thoiGianDuyet = db.Column(db.String(30))
    payment_status = db.Column(db.String(30))  # CHO_THANH_TOAN / DA_THANH_TOAN / TU_CHOI
    payment_method = db.Column(db.String(30))  # CASH / BANK / OTHER
    payment_ref = db.Column(db.String(120))
    proof_url = db.Column(db.Text)


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
        dialect = None
        try:
            dialect = db.engine.dialect.name
        except Exception:
            dialect = None

        # Local/demo (SQLite): auto tạo admin mặc định cho dễ dùng.
        # Production (Postgres/MySQL/...): chỉ tạo admin nếu bạn set env, tránh mật khẩu mặc định.
        admin_email = os.getenv("DEFAULT_ADMIN_EMAIL")
        admin_password = os.getenv("DEFAULT_ADMIN_PASSWORD")

        if dialect == "sqlite":
            admin_email = admin_email or "admin@smartbus.local"
            admin_password = admin_password or "admin123"

        if not admin_email or not admin_password:
            # Không tạo admin nếu thiếu credential (đặc biệt quan trọng khi deploy).
            # Bạn vẫn có thể đăng ký user thường và/hoặc tạo admin qua DB.
            pass
        else:
            admin = TaiKhoan(
                email=admin_email,
                mat_khau_hash=generate_password_hash(admin_password),
                vai_tro="ADMIN"
            )
            try:
                db.session.add(admin)
                db.session.commit()
            except IntegrityError:
                # Gunicorn nhiều worker có thể init đồng thời -> ignore nếu admin đã được tạo ở worker khác.
                db.session.rollback()

# SQLite alter helpers: add missing columns / indexes without migrations
def ensure_schema():
    # Helper này chỉ dành cho SQLite (demo/local). Khi deploy Postgres, hãy dùng migration.
    try:
        if db.engine.dialect.name != "sqlite":
            return
    except Exception:
        return
    try:
        with db.engine.begin() as conn:
            def _pragma_colnames(table):
                rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                names = set()
                for r in rows:
                    try:
                        names.add(r._mapping.get("name"))
                    except Exception:
                        try:
                            names.add(r["name"])
                        except Exception:
                            # sqlite pragma table_info: name ở index 1
                            try:
                                names.add(r[1])
                            except Exception:
                                pass
                names.discard(None)
                return names

            cols = _pragma_colnames("the_tu")
            if "loaiThe" not in cols:
                conn.execute(text("ALTER TABLE the_tu ADD COLUMN loaiThe VARCHAR(20)"))
            if "giaTri" not in cols:
                conn.execute(text("ALTER TABLE the_tu ADD COLUMN giaTri FLOAT"))
            if "nguoiDuyet" not in cols:
                conn.execute(text("ALTER TABLE the_tu ADD COLUMN nguoiDuyet VARCHAR(120)"))
            if "thoiGianDuyet" not in cols:
                conn.execute(text("ALTER TABLE the_tu ADD COLUMN thoiGianDuyet VARCHAR(30)"))
            if "payment_status" not in cols:
                conn.execute(text("ALTER TABLE the_tu ADD COLUMN payment_status VARCHAR(30)"))
            if "payment_method" not in cols:
                conn.execute(text("ALTER TABLE the_tu ADD COLUMN payment_method VARCHAR(30)"))
            if "payment_ref" not in cols:
                conn.execute(text("ALTER TABLE the_tu ADD COLUMN payment_ref VARCHAR(120)"))
            if "proof_url" not in cols:
                conn.execute(text("ALTER TABLE the_tu ADD COLUMN proof_url TEXT"))

            # TuyenXe: thêm khoảng cách, tần suất phút nếu thiếu
            route_cols = _pragma_colnames("tuyen_xe")
            if "giaVe" not in route_cols:
                conn.execute(text("ALTER TABLE tuyen_xe ADD COLUMN giaVe VARCHAR(50)"))
            if "soChuyenMoiNgay" not in route_cols:
                conn.execute(text("ALTER TABLE tuyen_xe ADD COLUMN soChuyenMoiNgay INTEGER"))
            if "thoiGianHoatDong" not in route_cols:
                conn.execute(text("ALTER TABLE tuyen_xe ADD COLUMN thoiGianHoatDong VARCHAR(100)"))
            if "ghiChu" not in route_cols:
                conn.execute(text("ALTER TABLE tuyen_xe ADD COLUMN ghiChu TEXT"))
            if "khoangCachKm" not in route_cols:
                conn.execute(text("ALTER TABLE tuyen_xe ADD COLUMN khoangCachKm FLOAT"))
            if "tanSuatPhut" not in route_cols:
                conn.execute(text("ALTER TABLE tuyen_xe ADD COLUMN tanSuatPhut INTEGER"))

            # ChuyenXe: thêm hướng (DI/VE) để tách lộ trình theo chiều chạy
            trip_cols = _pragma_colnames("chuyen_xe")
            if "huong" not in trip_cols:
                conn.execute(text("ALTER TABLE chuyen_xe ADD COLUMN huong VARCHAR(10)"))
                conn.execute(text("UPDATE chuyen_xe SET huong = 'DI' WHERE huong IS NULL OR TRIM(huong) = ''"))

            # VeXe: chuyển sang vé lượt (không theo ghế) bằng mã vé/QR
            ticket_cols = _pragma_colnames("ve_xe")
            if "maSoVe" not in ticket_cols:
                conn.execute(text("ALTER TABLE ve_xe ADD COLUMN maSoVe VARCHAR(50)"))
            if "thoiGianSuDung" not in ticket_cols:
                conn.execute(text("ALTER TABLE ve_xe ADD COLUMN thoiGianSuDung VARCHAR(30)"))

            try:
                conn.execute(text("""
                  CREATE UNIQUE INDEX IF NOT EXISTS idx_card_code_unique
                  ON the_tu (maSoThe)
                """))
            except Exception:
                pass

            try:
                conn.execute(text("""
                  CREATE UNIQUE INDEX IF NOT EXISTS idx_ticket_code_unique
                  ON ve_xe (maSoVe)
                """))
            except Exception:
                pass

            # Tránh tạo trùng chuyến theo tuyến/ngày/giờ/hướng khi auto-generate lịch
            try:
                conn.execute(text("""
                  CREATE UNIQUE INDEX IF NOT EXISTS idx_trip_unique_departure
                  ON chuyen_xe (tuyen_id, ngayKhoiHanh, gioKhoiHanh, huong)
                """))
            except Exception:
                # nếu DB đã có dữ liệu trùng, tránh làm app chết; code sẽ tự tránh trùng ở mức logic
                pass

            # Ngăn double-book ghế (trừ ghế đã hủy)
            try:
                conn.execute(text("""
                  CREATE UNIQUE INDEX IF NOT EXISTS idx_ve_unique_seat_active
                  ON ve_xe (chuyen_id, soGhe)
                  WHERE trangThai != 'DA_HUY'
                """))
            except Exception:
                pass
    except Exception as e:
        print("ensure_schema warning:", e)

with app.app_context():
    ensure_schema()


# ==================== HÀM TIỆN ÍCH ====================

def current_user():
    uid = session.get("user_id")
    if uid is None:
        return None
    return db.session.get(TaiKhoan, uid)


def ensure_customer(user):
    """Đảm bảo tài khoản có hồ sơ khách hàng, tạo tối thiểu nếu chưa có."""
    if not user:
        return None
    if user.khach_hang:
        return user.khach_hang

    kh = KhachHang(
        hoTen=(user.email or "Khach hang").split("@")[0],
        tai_khoan_id=user.id,
        ngayDangKy=datetime.utcnow().strftime("%Y-%m-%d"),
    )
    db.session.add(kh)
    db.session.flush()
    return kh


def generate_card_code():
    # sinh mã ngẫu nhiên 10 ký tự (không lộ timestamp)
    import random
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    core = "".join(random.choice(alphabet) for _ in range(10))
    return f"SB-{core}"


def normalize_direction(value):
    v = (value or "DI").strip().upper()
    return v if v in ("DI", "VE") else "DI"


def _parse_operating_window_minutes(raw):
    """
    Parse chuỗi kiểu "05:30 - 17:50" / "05:30 – 17:50" -> (start_min, end_min).
    """
    if not raw:
        return None

    # chấp nhận "05:30", "05-30", "05h30"
    matches = re.findall(r"(\d{1,2})\s*[:h\-]\s*(\d{2})", str(raw).lower())
    if len(matches) < 2:
        return None

    try:
        h1, m1 = int(matches[0][0]), int(matches[0][1])
        h2, m2 = int(matches[1][0]), int(matches[1][1])
    except Exception:
        return None

    if not (0 <= h1 <= 23 and 0 <= h2 <= 23 and 0 <= m1 <= 59 and 0 <= m2 <= 59):
        return None

    start = h1 * 60 + m1
    end = h2 * 60 + m2
    if end <= start:
        return None
    return (start, end)


def _compute_headway_minutes(tuyen, window_minutes, dirs_count=2):
    """
    Tính headway (phút/chuyến).
    - Ưu tiên `tanSuatPhut` nếu có.
    - Fallback từ `soChuyenMoiNgay` (mặc định hiểu là tổng DI+VE/ngày).
    """
    if tuyen and tuyen.tanSuatPhut:
        try:
            v = int(tuyen.tanSuatPhut)
            return v if v > 0 else None
        except Exception:
            pass

    if tuyen and tuyen.soChuyenMoiNgay and window_minutes:
        try:
            trips_total = int(tuyen.soChuyenMoiNgay)
            if trips_total <= 1:
                return None

            dirs = max(1, int(dirs_count or 1))
            trips_per_dir = max(1, int(round(trips_total / dirs)))
            if trips_per_dir <= 1:
                return None

            # N chuyến trong ngày => có (N-1) khoảng cách giữa các chuyến trong khung giờ hoạt động.
            raw = float(window_minutes) / float(trips_per_dir - 1)
            headway = int(round(raw))
            headway = max(5, min(headway, 180))
            return headway
        except Exception:
            return None

    return None


def ensure_upcoming_trips(tuyen, now=None, horizon_min=None):
    """
    Bus đô thị: tự sinh chuyến sắp tới theo khung giờ + tần suất.
    - Chỉ sinh trong khoảng [now, now + horizon] để tránh DB phình to.
    - Sinh theo hướng DI/VE nếu tuyến có dữ liệu trạm cho hướng đó.
    """
    if not tuyen:
        return 0

    now = now or datetime.now()
    horizon_min = BUS_SCHEDULE_HORIZON_MIN if horizon_min is None else int(horizon_min)
    horizon_min = max(30, min(horizon_min, 24 * 60))

    window = _parse_operating_window_minutes(tuyen.thoiGianHoatDong)
    if not window:
        return 0
    start_min, end_min = window
    window_minutes = end_min - start_min

    # xác định hướng có dữ liệu trạm
    dirs = []
    for d in ("DI", "VE"):
        st = stop_stats_for_direction(tuyen, d)
        if st.get("stops", 0) > 0:
            dirs.append(d)

    if not dirs:
        return 0

    # nếu chỉ có 1 hướng dữ liệu, vẫn hiểu là tuyến 2 chiều (DI+VE) để tính headway từ "số chuyến/ngày"
    dirs_count_for_schedule = 2 if len(dirs) == 1 else len(dirs)

    headway = _compute_headway_minutes(tuyen, window_minutes, dirs_count=dirs_count_for_schedule)
    if not headway:
        return 0

    # chỉ sinh cho hôm nay (demo). Nếu muốn: mở rộng sang ngày kế tiếp.
    date_str = now.strftime("%Y-%m-%d")
    now_min = now.hour * 60 + now.minute

    from_min = max(start_min, now_min)
    to_min = min(end_min, from_min + horizon_min)
    if to_min < from_min:
        return 0

    # căn về mốc headway tính từ start_min
    offset = (from_min - start_min) % headway
    first = from_min if offset == 0 else (from_min + (headway - offset))

    times = []
    t = first
    while t <= to_min:
        times.append(f"{t // 60:02d}:{t % 60:02d}")
        t += headway

    if not times:
        return 0

    existing = (
        ChuyenXe.query
        .filter(ChuyenXe.tuyen_id == tuyen.maTuyen, ChuyenXe.ngayKhoiHanh == date_str)
        .with_entities(ChuyenXe.gioKhoiHanh, ChuyenXe.huong)
        .all()
    )
    existing_set = {(normalize_direction(h), g) for (g, h) in existing if g}

    new_rows = []
    for d in dirs:
        for gio in times:
            key = (d, gio)
            if key in existing_set:
                continue
            new_rows.append(
                ChuyenXe(tuyen_id=tuyen.maTuyen, ngayKhoiHanh=date_str, gioKhoiHanh=gio, huong=d)
            )

    if not new_rows:
        return 0

    db.session.add_all(new_rows)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        # Nếu đụng unique index do race condition, bỏ qua.
        return 0

    return len(new_rows)


def parse_route_price(tuyen, fallback=50000):
    """Lấy giá vé từ tuyen.giaVe (string) nếu parse được, ngược lại dùng fallback."""
    if tuyen and tuyen.giaVe:
        digits = "".join(ch for ch in tuyen.giaVe if ch.isdigit())
        if digits:
            try:
                return float(digits)
            except ValueError:
                pass
    return float(fallback)

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
        "distance_km": tuyen.khoangCachKm,
        "operating_hours": tuyen.thoiGianHoatDong,
        "fare": tuyen.giaVe,
        "frequency_min": tuyen.tanSuatPhut,
        "trips_per_day": tuyen.soChuyenMoiNgay,
        "directions": dir_stats,
        "totals": {
            "stops": total_stops,
            "with_geo": total_geo,
            "percent_with_geo": percent,
        },
        "data_status": status,
    }


def _ceil_div_int(n, d):
    if d <= 0:
        return 0
    return -(-n // d)


def _stops_signature(stops):
    payload = [
        (
            int(s.maTram),
            int(s.thuTuTrenTuyen or 0),
            float(s.lat) if s.lat is not None else None,
            float(s.lng) if s.lng is not None else None,
        )
        for s in stops
    ]
    raw = repr(payload).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def _compute_stop_offsets_fallback(coord_stops):
    """
    Fallback tính offset theo khoảng cách Haversine + tốc độ trung bình.
    coord_stops: list TramDung có lat/lng theo thứ tự.
    """
    def haversine_m(lat1, lon1, lat2, lon2):
        r = 6371000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
        return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    speed_mps = max(3.0, float(BUS_FALLBACK_SPEED_KMH) * 1000.0 / 3600.0)
    offsets = {coord_stops[0].maTram: 0}
    dist_acc = {coord_stops[0].maTram: 0.0}

    cum_s = 0.0
    cum_m = 0.0
    for i in range(len(coord_stops) - 1):
        a = coord_stops[i]
        b = coord_stops[i + 1]
        seg_m = haversine_m(float(a.lat), float(a.lng), float(b.lat), float(b.lng))
        seg_s = seg_m / speed_mps
        cum_s += seg_s + float(BUS_STOP_DWELL_SEC)
        cum_m += seg_m
        offsets[b.maTram] = cum_s
        dist_acc[b.maTram] = cum_m

    return offsets, dist_acc


def get_stop_offsets(tuyen, dir_):
    """
    Tính thời gian dự kiến dựa trên khoảng cách địa lý (Haversine).
    Ép buộc dùng chế độ fallback để đảm bảo luôn có dữ liệu mà không cần gọi API OSRM.
    """
    dir_clean = normalize_direction(dir_)
    stops = _query_stops_by_direction(tuyen, dir_clean).all()
    stops.sort(key=lambda s: (s.thuTuTrenTuyen or 0, s.maTram or 0))

    coord_stops = [s for s in stops if s.lat is not None and s.lng is not None]
    if len(coord_stops) < 2:
        return {"ok": False, "error": "Tuyến chưa đủ 2 trạm có tọa độ.", "items": []}

    # --- SỬA ĐỔI: Luôn dùng tính toán nội bộ (Fallback) ---
    # Tốc độ giả định: 22km/h (Bạn có thể sửa số này ở dòng cấu hình BUS_FALLBACK_SPEED_KMH)
    offsets, dist_acc = _compute_stop_offsets_fallback(coord_stops)
    
    value = {
        "ok": True, 
        "source": "fallback (simulation)", 
        "offsets": offsets, 
        "dist_m": dist_acc, 
        "items": stops
    }
    return value

    sig = _stops_signature(coord_stops)
    cache_key = (int(tuyen.maTuyen), dir_clean, sig)
    now_ts = time.time()
    hit = _STOP_OFFSET_CACHE.get(cache_key)
    if hit and (now_ts - hit["ts"]) < max(30, int(STOP_OFFSET_CACHE_TTL_SEC)):
        return hit["value"]

    # Nếu quá nhiều điểm, fallback để tránh 413/timeout
    if len(coord_stops) > int(OSRM_MAX_COORDS):
        offsets, dist_acc = _compute_stop_offsets_fallback(coord_stops)
        value = {"ok": True, "source": "fallback", "offsets": offsets, "dist_m": dist_acc, "items": stops}
        _STOP_OFFSET_CACHE[cache_key] = {"ts": now_ts, "value": value}
        return value

    coords = ";".join(f"{float(s.lng)},{float(s.lat)}" for s in coord_stops)
    url = f"{OSRM_BASE_URL}/route/v1/{OSRM_PROFILE}/{coords}"
    params = {"overview": "false", "steps": "false"}

    try:
        r = requests.get(url, params=params, timeout=OSRM_TIMEOUT)
        j = r.json() if r.content else {}
        if r.status_code != 200 or j.get("code") != "Ok" or not j.get("routes"):
            raise RuntimeError("OSRM không trả route")

        route = j["routes"][0]
        legs = route.get("legs") or []
        if len(legs) != len(coord_stops) - 1:
            raise RuntimeError("OSRM legs không khớp số điểm")

        offsets = {coord_stops[0].maTram: 0.0}
        dist_acc = {coord_stops[0].maTram: 0.0}
        cum_s = 0.0
        cum_m = 0.0
        for i, leg in enumerate(legs):
            dur = float(leg.get("duration") or 0.0) * float(BUS_OSRM_DURATION_FACTOR)
            dist = float(leg.get("distance") or 0.0)
            cum_s += dur + float(BUS_STOP_DWELL_SEC)
            cum_m += dist
            offsets[coord_stops[i + 1].maTram] = cum_s
            dist_acc[coord_stops[i + 1].maTram] = cum_m

        value = {"ok": True, "source": "osrm", "offsets": offsets, "dist_m": dist_acc, "items": stops}
        _STOP_OFFSET_CACHE[cache_key] = {"ts": now_ts, "value": value}
        return value
    except Exception as e:
        offsets, dist_acc = _compute_stop_offsets_fallback(coord_stops)
        value = {"ok": True, "source": "fallback", "offsets": offsets, "dist_m": dist_acc, "items": stops, "warn": str(e)}
        _STOP_OFFSET_CACHE[cache_key] = {"ts": now_ts, "value": value}
        return value


def compute_next_stop_etas(tuyen, dir_, at=None):
    at = at or datetime.now()
    window = _parse_operating_window_minutes(tuyen.thoiGianHoatDong)
    if not window:
        return {"ok": False, "error": "Tuyến chưa có khung giờ hoạt động (thoiGianHoatDong).", "items": []}

    start_min, end_min = window
    window_minutes = end_min - start_min

    # nếu chỉ có 1 hướng dữ liệu, vẫn hiểu tuyến 2 chiều để suy ra headway từ "số chuyến/ngày"
    dirs = []
    for d in ("DI", "VE"):
        st = stop_stats_for_direction(tuyen, d)
        if st.get("stops", 0) > 0:
            dirs.append(d)
    dirs_count_for_schedule = 2 if len(dirs) == 1 else max(1, len(dirs))

    headway_min = _compute_headway_minutes(tuyen, window_minutes, dirs_count=dirs_count_for_schedule)
    if not headway_min:
        return {"ok": False, "error": "Tuyến chưa có tần suất hoặc số chuyến/ngày hợp lệ.", "items": []}

    offsets_data = get_stop_offsets(tuyen, dir_)
    if not offsets_data.get("ok"):
        return {"ok": False, "error": offsets_data.get("error") or "Không tính được offset trạm.", "items": []}

    base = datetime.combine(at.date(), datetime.min.time())
    at_s = int((at - base).total_seconds())

    start_s = int(start_min * 60)
    end_s = int(end_min * 60)
    headway_s = int(headway_min * 60)

    out_items = []
    for s in offsets_data.get("items") or []:
        offset_s = offsets_data["offsets"].get(s.maTram)
        dist_m = offsets_data.get("dist_m", {}).get(s.maTram)

        eta_iso = None
        eta_hhmm = None
        eta_in_min = None

        if offset_s is not None:
            target_depart_s = max(start_s, at_s - int(round(float(offset_s))))
            k = _ceil_div_int(max(0, target_depart_s - start_s), headway_s)
            depart_s = start_s + k * headway_s
            if depart_s <= end_s:
                eta_dt = base + timedelta(seconds=(depart_s + float(offset_s)))
                eta_iso = eta_dt.isoformat(timespec="seconds")
                eta_hhmm = eta_dt.strftime("%H:%M")
                eta_in_min = int(round((eta_dt - at).total_seconds() / 60.0))

        out_items.append({
            "stop_id": s.maTram,
            "order": s.thuTuTrenTuyen,
            "name": s.tenTram,
            "address": s.diaChi,
            "lat": float(s.lat) if s.lat is not None else None,
            "lng": float(s.lng) if s.lng is not None else None,
            "offset_s": float(offset_s) if offset_s is not None else None,
            "distance_m": float(dist_m) if dist_m is not None else None,
            "eta_iso": eta_iso,
            "eta_time": eta_hhmm,
            "eta_in_min": eta_in_min,
        })

    return {
        "ok": True,
        "route_id": tuyen.maTuyen,
        "route_code": tuyen.maHienThi,
        "direction": normalize_direction(dir_),
        "as_of": at.isoformat(timespec="seconds"),
        "operating_hours": tuyen.thoiGianHoatDong,
        "headway_min": headway_min,
        "offset_source": offsets_data.get("source"),
        "items": out_items,
    }


@app.context_processor
def inject_user():
    def static_url(filename: str):
        safe_name = filename.lstrip("/\\")
        file_path = os.path.join(app.root_path, "static", safe_name)
        try:
            version = int(os.path.getmtime(file_path))
        except OSError:
            version = int(time.time())

        return url_for("static", filename=safe_name, v=version)

    return dict(user=current_user(), static_url=static_url)


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
        password2 = request.form.get("password2")

        if not email or not password:
            flash("Email và mật khẩu không được để trống.")
            return redirect(url_for("register"))

        if len(password) < 6:
            flash("Mật khẩu nên có tối thiểu 6 ký tự.")
            return redirect(url_for("register"))

        if password2 is not None and password != password2:
            flash("Mật khẩu nhập lại không khớp.")
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

    now = datetime.now()
    ensure_upcoming_trips(tuyen, now=now)

    today = now.strftime("%Y-%m-%d")
    now_min = now.hour * 60 + now.minute

    def _to_min(hhmm):
        m = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{2})\s*$", str(hhmm or ""))
        if not m:
            return None
        h = int(m.group(1))
        mi = int(m.group(2))
        if h < 0 or h > 23 or mi < 0 or mi > 59:
            return None
        return h * 60 + mi

    all_today = (
        ChuyenXe.query
        .filter(ChuyenXe.tuyen_id == tuyen_id, ChuyenXe.ngayKhoiHanh == today)
        .order_by(ChuyenXe.gioKhoiHanh.asc(), ChuyenXe.huong.asc(), ChuyenXe.maChuyen.asc())
        .all()
    )

    # chỉ lấy chuyến sắp tới (giữ gọn UI) – bus đô thị thường hiển thị upcoming departures
    trips = []
    for t in all_today:
        t_min = _to_min(t.gioKhoiHanh)
        if t_min is None:
            continue
        if t_min >= now_min - 5:
            trips.append(t)
        if len(trips) >= 12:
            break

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
    # Bus đô thị: chi tiết chuyến dùng để xem lịch/ETA, không phải đặt vé.
    # Cho phép khách xem (public) để tra cứu lịch trình theo tuyến/trạm.

    direction = normalize_direction(getattr(trip, "huong", None))

    # lấy trạm theo hướng để hiển thị lộ trình + map (bus đô thị: tách DI/VE)
    danh_sach_tram = _query_stops_by_direction(tuyen, direction).all()
    stops_geo = build_stops_geo(danh_sach_tram, route_code=tuyen.maHienThi)

    trip_dt = None
    try:
        trip_dt = datetime.strptime(f"{trip.ngayKhoiHanh} {trip.gioKhoiHanh}", "%Y-%m-%d %H:%M")
    except Exception:
        trip_dt = None
    is_past_trip = bool(trip_dt and trip_dt < datetime.utcnow())

    stop_times = []
    offset_source = None
    if trip_dt and danh_sach_tram:
        try:
            offsets_data = get_stop_offsets(tuyen, direction)
            if offsets_data.get("ok"):
                offsets = offsets_data.get("offsets") or {}
                dist_m = offsets_data.get("dist_m") or {}
                offset_source = offsets_data.get("source")

                for s in danh_sach_tram:
                    off_s = offsets.get(s.maTram)
                    dist_km = None
                    if dist_m.get(s.maTram) is not None:
                        dist_km = round(float(dist_m.get(s.maTram)) / 1000.0, 2)

                    eta_dt = trip_dt + timedelta(seconds=float(off_s)) if off_s is not None else None
                    stop_times.append({
                        "stop": s,
                        "eta_time": eta_dt.strftime("%H:%M") if eta_dt else None,
                        "eta_iso": eta_dt.isoformat(timespec="seconds") if eta_dt else None,
                        "offset_min": int(round(float(off_s) / 60.0)) if off_s is not None else None,
                        "distance_km": dist_km,
                    })
        except Exception:
            stop_times = []
            offset_source = None

    return render_template(
        "trip_detail.html",
        trip=trip,
        tuyen=tuyen,
        stops=danh_sach_tram,
        stop_times=stop_times,
        offset_source=offset_source,
        stops_geo=stops_geo,
        direction=direction,
        is_past_trip=is_past_trip,
        is_admin_mode=is_admin_mode,
        user=user,
    )


@app.route("/stops/<int:stop_id>")
def stop_detail(stop_id):
    """
    Chi tiết trạm (public):
    - Hiển thị thông tin trạm (thuộc tuyến + hướng DI/VE)
    - Liệt kê các chuyến sắp tới sẽ đi qua trạm (ETA ước tính theo offset trạm)
    """
    stop = TramDung.query.get_or_404(stop_id)
    tuyen = stop.tuyen
    direction = normalize_direction(getattr(stop, "huong", None))

    now = datetime.now()

    # backfill để không bỏ sót chuyến đã xuất bến nhưng chưa tới trạm
    offsets_data = get_stop_offsets(tuyen, direction)
    offset_s = None
    if offsets_data.get("ok"):
        offset_s = offsets_data.get("offsets", {}).get(stop.maTram)

    backfill_min = 30
    try:
        if offset_s is not None:
            backfill_min = max(30, min(180, int(math.ceil(float(offset_s) / 60.0)) + 5))
    except Exception:
        backfill_min = 30

    ensure_upcoming_trips(
        tuyen,
        now=(now - timedelta(minutes=backfill_min)),
        horizon_min=(backfill_min + BUS_SCHEDULE_HORIZON_MIN),
    )

    today = now.strftime("%Y-%m-%d")

    try:
        limit = int(request.args.get("limit") or 20)
    except Exception:
        limit = 20
    limit = max(5, min(limit, 60))

    upcoming = []
    trips = (
        ChuyenXe.query
        .filter(
            ChuyenXe.tuyen_id == tuyen.maTuyen,
            ChuyenXe.ngayKhoiHanh == today,
            ChuyenXe.huong == direction,
        )
        .order_by(ChuyenXe.gioKhoiHanh.asc(), ChuyenXe.maChuyen.asc())
        .all()
    )

    for t in trips:
        try:
            if not (t.ngayKhoiHanh and t.gioKhoiHanh):
                continue
            depart_dt = datetime.strptime(f"{t.ngayKhoiHanh} {t.gioKhoiHanh}", "%Y-%m-%d %H:%M")
        except Exception:
            continue

        eta_dt = None
        if offset_s is not None:
            try:
                eta_dt = depart_dt + timedelta(seconds=float(offset_s))
            except Exception:
                eta_dt = None

        # Nếu không có offset, fallback lọc theo giờ xuất bến (ít ý nghĩa với trạm giữa tuyến)
        ref_dt = eta_dt or depart_dt
        if ref_dt < (now - timedelta(minutes=1)):
            continue

        eta_in_min = int(round((ref_dt - now).total_seconds() / 60.0))
        eta_in_min = max(0, eta_in_min)

        upcoming.append({
            "trip_id": t.maChuyen,
            "date": t.ngayKhoiHanh,
            "depart_time": t.gioKhoiHanh,
            "direction": direction,
            "eta_time": ref_dt.strftime("%H:%M"),
            "eta_iso": ref_dt.isoformat(timespec="seconds"),
            "eta_in_min": eta_in_min,
            "detail_url": url_for("trip_detail", trip_id=t.maChuyen),
        })

    upcoming.sort(key=lambda x: (x.get("eta_iso") or "9999", x.get("trip_id") or 0))
    upcoming = upcoming[:limit]

    stop_geo = {
        "id": stop.maTram,
        "name": stop.tenTram,
        "address": stop.diaChi,
        "lat": float(stop.lat) if stop.lat is not None else None,
        "lng": float(stop.lng) if stop.lng is not None else None,
        "order": stop.thuTuTrenTuyen,
        "dir": direction,
        "direction": direction,
        "route_code": tuyen.maHienThi,
    }

    return render_template(
        "stop_detail.html",
        stop=stop,
        tuyen=tuyen,
        direction=direction,
        stop_geo=stop_geo,
        upcoming=upcoming,
        offset_source=offsets_data.get("source") if offsets_data.get("ok") else None,
        offset_ok=bool(offset_s is not None),
    )



@app.route("/card-register", methods=["GET", "POST"])
def card_register():
    # Đảm bảo schema đã có cột loaiThe/giaTri (phòng trường hợp DB cũ)
    ensure_schema()
    user = current_user()
    if not user:
        flash("Bạn phải đăng nhập để đăng ký thẻ.")
        return redirect(url_for("login", next=request.path))
    if user.vai_tro == "ADMIN":
        flash("Admin không tự đăng ký thẻ. Vào trang Admin thẻ để quản lý/duyệt.")
        return redirect(url_for("admin_cards"))

    kh = ensure_customer(user)

    pricing = {
        "THANG": 250000,
        "QUY": 650000,
        "NAM": 2400000,
    }
    durations = {
        "THANG": 30,
        "QUY": 90,
        "NAM": 365,
    }

    existing_cards = (
        TheTu.query
        .filter_by(khach_hang_id=kh.maKH)
        .order_by(TheTu.maThe.desc())
        .all()
    )

    if request.method == "POST":
        loai = (request.form.get("loaiThe") or "THANG").upper()
        if loai not in pricing:
            loai = "THANG"

        start_raw = request.form.get("ngayBatDau") or datetime.utcnow().strftime("%Y-%m-%d")
        try:
            start_date = datetime.strptime(start_raw, "%Y-%m-%d").date()
        except ValueError:
            flash("Ngày bắt đầu không hợp lệ.")
            return redirect(url_for("card_register"))

        if start_date < datetime.utcnow().date():
            flash("Ngày bắt đầu không được trong quá khứ.")
            return redirect(url_for("card_register"))

        end_date = start_date + timedelta(days=durations.get(loai, 30))
        code = generate_card_code()

        # phòng trùng lặp mã (hiếm)
        existing = TheTu.query.filter_by(maSoThe=code).first()
        if existing:
            code = generate_card_code()

        payment_method = (request.form.get("payment_method") or "CASH").upper()
        payment_ref = (request.form.get("payment_ref") or "").strip()
        proof_url = (request.form.get("proof_url") or "").strip()

        card = TheTu(
            khach_hang_id=kh.maKH,
            maSoThe=code,
            loaiThe=loai,
            giaTri=pricing.get(loai),
            ngayBatDau=start_date.isoformat(),
            ngayHetHan=end_date.isoformat(),
            trangThai="CHO_KICH_HOAT",
            payment_status="CHO_THANH_TOAN",
            payment_method=payment_method,
            payment_ref=payment_ref,
            proof_url=proof_url or None,
        )
        db.session.add(card)
        db.session.commit()
        flash(f"Đăng ký thẻ thành công! Mã thẻ: {card.maSoThe}. Trạng thái: {card.trangThai}.")
        return redirect(url_for("cards"))

    return render_template(
        "card_register.html",
        pricing=pricing,
        existing_cards=existing_cards,
        user=user,
        khach_hang=kh,
        today_str=datetime.utcnow().strftime("%Y-%m-%d"),
    )


@app.route("/cards")
def cards():
    ensure_schema()
    user = current_user()
    if not user:
        flash("Bạn phải đăng nhập để xem thẻ.")
        return redirect(url_for("login", next=request.path))
    if user.vai_tro == "ADMIN":
        flash("Admin không có thẻ cá nhân. Vui lòng quản lý tại trang Admin thẻ.")
        return redirect(url_for("admin_cards"))

    kh = ensure_customer(user)

    cards = (
        TheTu.query
        .filter_by(khach_hang_id=kh.maKH)
        .order_by(TheTu.maThe.desc())
        .all()
    )
    return render_template("cards.html", cards=cards, user=user)


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
        khoang_cach = request.form.get("khoangCachKm")
        thoi_gian_hd = (request.form.get("thoiGianHoatDong") or "").strip()
        tan_suat = request.form.get("tanSuatPhut")
        so_chuyen = request.form.get("soChuyenMoiNgay")
        gia_ve = (request.form.get("giaVe") or "").strip()

        if not ma_tuyen_display or not ten_tuyen:
            flash("Mã tuyến và tên tuyến không được để trống!")
            return redirect(url_for("admin_routes"))

        # parse numeric inputs
        try:
            khoang_cach_val = float(khoang_cach) if khoang_cach else None
        except Exception:
            flash("Khoảng cách (km) không hợp lệ.")
            return redirect(url_for("admin_routes", edit=ma_tuyen_id) if ma_tuyen_id else url_for("admin_routes"))

        try:
            tan_suat_val = int(tan_suat) if tan_suat else None
        except Exception:
            flash("Tần suất (phút/chuyến) không hợp lệ.")
            return redirect(url_for("admin_routes", edit=ma_tuyen_id) if ma_tuyen_id else url_for("admin_routes"))

        try:
            so_chuyen_val = int(so_chuyen) if so_chuyen else None
        except Exception:
            flash("Số chuyến/ngày không hợp lệ.")
            return redirect(url_for("admin_routes", edit=ma_tuyen_id) if ma_tuyen_id else url_for("admin_routes"))

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
            tuyen.khoangCachKm = khoang_cach_val
            tuyen.thoiGianHoatDong = thoi_gian_hd or None
            tuyen.tanSuatPhut = tan_suat_val
            tuyen.soChuyenMoiNgay = so_chuyen_val
            tuyen.giaVe = gia_ve or None
            db.session.commit()
            flash("Đã cập nhật tuyến thành công!")
            return redirect(url_for("admin_routes"))

        # Nếu không có ID: tạo mới hoặc update theo maHienThi
        tuyen = TuyenXe.query.filter_by(maHienThi=ma_tuyen_display).first()
        if tuyen:
            tuyen.tenTuyen = ten_tuyen
            tuyen.diemBatDau = diem_bd
            tuyen.diemKetThuc = diem_kt
            tuyen.khoangCachKm = khoang_cach_val if khoang_cach_val is not None else tuyen.khoangCachKm
            tuyen.thoiGianHoatDong = thoi_gian_hd or tuyen.thoiGianHoatDong
            tuyen.tanSuatPhut = tan_suat_val if tan_suat_val is not None else tuyen.tanSuatPhut
            tuyen.soChuyenMoiNgay = so_chuyen_val if so_chuyen_val is not None else tuyen.soChuyenMoiNgay
            tuyen.giaVe = gia_ve or tuyen.giaVe
            flash("Đã cập nhật tuyến cũ thành công!")
        else:
            tuyen = TuyenXe(
                maHienThi=ma_tuyen_display,
                tenTuyen=ten_tuyen,
                diemBatDau=diem_bd,
                diemKetThuc=diem_kt,
                khoangCachKm=khoang_cach_val,
                thoiGianHoatDong=thoi_gian_hd or None,
                tanSuatPhut=tan_suat_val,
                soChuyenMoiNgay=so_chuyen_val,
                giaVe=gia_ve or None,
            )
            db.session.add(tuyen)
            flash("Đã thêm tuyến mới thành công!")

        db.session.commit()
        return redirect(url_for("admin_routes"))

    danh_sach_tuyen = TuyenXe.query.order_by(TuyenXe.maTuyen).all()
    return render_template("admin_routes.html", routes=danh_sach_tuyen, edit_route=edit_route)


@app.route("/admin/cards", methods=["GET", "POST"])
def admin_cards():
    ensure_schema()
    user = current_user()
    if not user or user.vai_tro != "ADMIN":
        flash("Bạn không có quyền truy cập!")
        return redirect(url_for("home"))

    pricing = {"THANG": 250000, "QUY": 650000, "NAM": 2400000}
    durations = {"THANG": 30, "QUY": 90, "NAM": 365}

    if request.method == "POST":
        action = request.form.get("action")
        card_id = request.form.get("card_id")
        card = TheTu.query.get(card_id)
        if not card:
            flash("Không tìm thấy thẻ.")
            return redirect(url_for("admin_cards"))

        if action == "activate":
            if card.payment_status != "DA_THANH_TOAN":
                flash("Chưa xác nhận đã thanh toán, không thể kích hoạt.")
                return redirect(url_for("admin_cards"))
            card.trangThai = "KICH_HOAT"
            card.nguoiDuyet = user.email
            card.thoiGianDuyet = datetime.utcnow().isoformat(timespec="seconds")
            # nếu chưa có ngày hết hạn, tính theo loại thẻ
            try:
                start_date = datetime.strptime(card.ngayBatDau, "%Y-%m-%d").date() if card.ngayBatDau else datetime.utcnow().date()
            except Exception:
                start_date = datetime.utcnow().date()
            card.ngayBatDau = start_date.isoformat()
            days = durations.get(card.loaiThe or "THANG", 30)
            card.ngayHetHan = (start_date + timedelta(days=days)).isoformat()
            if not card.giaTri:
                card.giaTri = pricing.get(card.loaiThe or "THANG")
            db.session.commit()
            flash(f"Đã kích hoạt thẻ {card.maSoThe}.")
        elif action == "lock":
            card.trangThai = "TAM_KHOA"
            card.nguoiDuyet = user.email
            card.thoiGianDuyet = datetime.utcnow().isoformat(timespec="seconds")
            db.session.commit()
            flash(f"Đã khóa tạm thẻ {card.maSoThe}.")
        elif action == "pending":
            card.trangThai = "CHO_KICH_HOAT"
            db.session.commit()
            flash(f"Đã chuyển thẻ {card.maSoThe} về trạng thái chờ.")
        elif action == "mark_paid":
            card.payment_status = "DA_THANH_TOAN"
            card.payment_ref = request.form.get("payment_ref") or card.payment_ref
            card.payment_method = request.form.get("payment_method") or card.payment_method
            db.session.commit()
            flash(f"Đã đánh dấu đã nhận tiền cho thẻ {card.maSoThe}.")
        elif action == "delete":
            db.session.delete(card)
            db.session.commit()
            flash(f"Đã xóa thẻ {card.maSoThe}.")
        else:
            flash("Hành động không hợp lệ.")

        return redirect(url_for("admin_cards"))

    status_filter = request.args.get("status")
    q = TheTu.query
    if status_filter:
        q = q.filter(TheTu.trangThai == status_filter)
    cards = q.order_by(TheTu.maThe.desc()).all()

    # preload khách hàng để hiển thị tên
    khach_ids = {c.khach_hang_id for c in cards if c.khach_hang_id}
    khach_map = {}
    if khach_ids:
        for kh in KhachHang.query.filter(KhachHang.maKH.in_(khach_ids)).all():
            khach_map[kh.maKH] = kh

    return render_template(
        "admin_cards.html",
        cards=cards,
        khach_map=khach_map,
        status_filter=status_filter,
        pricing=pricing,
        user=user,
    )

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

        # Tách hướng DI/VE để quản lý đúng chiều chạy
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
                tram.huong = huong
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
                huong=huong,
                tuyen_id=tuyen_id,
            )
            db.session.add(tram)
            db.session.commit()
            flash("Đã thêm trạm dừng mới.")

        return redirect(url_for("admin_route_stops", tuyen_id=tuyen_id))

    # Sắp xếp theo hướng rồi theo thứ tự trạm (dễ nhìn + đúng luồng)
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
            huong = normalize_direction(request.form.get("huong"))

            if not ngay or not gio:
                flash("Ngày và giờ khởi hành không được để trống.")
            else:
                trip = ChuyenXe(
                    tuyen_id=tuyen.maTuyen,
                    ngayKhoiHanh=ngay,
                    gioKhoiHanh=gio,
                    huong=huong,
                )
                db.session.add(trip)
                try:
                    db.session.commit()
                    flash("Đã thêm chuyến mới.")
                except Exception:
                    db.session.rollback()
                    flash("Không thể thêm chuyến (có thể trùng ngày/giờ/hướng).")

        elif action == "edit_trip":
            trip_id = request.form.get("trip_id")
            ngay = request.form.get("ngayKhoiHanh")
            gio = request.form.get("gioKhoiHanh")
            huong = normalize_direction(request.form.get("huong"))

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
                    trip.huong = huong
                    try:
                        db.session.commit()
                        flash("Đã cập nhật chuyến.")
                    except Exception:
                        db.session.rollback()
                        flash("Không thể cập nhật chuyến (có thể trùng ngày/giờ/hướng).")

        return redirect(url_for("admin_route_trips", tuyen_id=tuyen_id))

    danh_sach_chuyen = (
        ChuyenXe.query
        .filter_by(tuyen_id=tuyen.maTuyen)
        .order_by(ChuyenXe.ngayKhoiHanh.asc(), ChuyenXe.gioKhoiHanh.asc(), ChuyenXe.huong.asc(), ChuyenXe.maChuyen.asc())
        .all()
    )
    danh_sach_tram = (
        TramDung.query
        .filter_by(tuyen_id=tuyen.maTuyen)
        .order_by(TramDung.thuTuTrenTuyen)
        .all()
    )
    # sắp xếp rõ DI trước, VE sau (DI mặc định nếu dữ liệu cũ thiếu huong)
    danh_sach_tram.sort(key=lambda s: (normalize_direction(getattr(s, "huong", None)), int(s.thuTuTrenTuyen or 0), int(s.maTram or 0)))
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

@app.route("/api/routes/<int:tuyen_id>/endpoints")
def api_route_endpoints(tuyen_id):
    tuyen = TuyenXe.query.get_or_404(tuyen_id)

    def pick_endpoints(dir_):
        stops = _query_stops_by_direction(tuyen, dir_).all()
        pts = [s for s in stops if s.lat is not None and s.lng is not None]
        pts.sort(key=lambda s: (s.thuTuTrenTuyen or 0, s.maTram or 0))
        if len(pts) < 2:
            return None
        a, b = pts[0], pts[-1]
        return {
            "direction": dir_,
            "start": {"lat": float(a.lat), "lng": float(a.lng), "name": a.tenTram, "order": a.thuTuTrenTuyen},
            "end": {"lat": float(b.lat), "lng": float(b.lng), "name": b.tenTram, "order": b.thuTuTrenTuyen},
        }

    data = pick_endpoints("DI") or pick_endpoints("VE")
    if not data:
        return jsonify({"ok": False, "error": "Tuyến chưa đủ 2 trạm có tọa độ để vẽ tổng quan."})

    return jsonify({"ok": True, "route_id": tuyen.maTuyen, "route_code": tuyen.maHienThi, **data})


@app.route("/api/routes/<int:tuyen_id>/trips")
def api_route_trips(tuyen_id):
    # "Chuyến sắp tới" cho dashboard /routes
    tuyen = TuyenXe.query.get_or_404(tuyen_id)

    try:
        limit = int(request.args.get("limit") or 12)
    except Exception:
        limit = 12
    limit = max(1, min(limit, 50))

    now = datetime.now()
    ensure_upcoming_trips(tuyen, now=now)
    today = now.strftime("%Y-%m-%d")

    items = []
    for t in (
        ChuyenXe.query
        .filter(ChuyenXe.tuyen_id == tuyen_id, ChuyenXe.ngayKhoiHanh == today)
        .order_by(ChuyenXe.gioKhoiHanh.asc(), ChuyenXe.huong.asc(), ChuyenXe.maChuyen.asc())
        .all()
    ):
        dt = None
        try:
            if t.ngayKhoiHanh and t.gioKhoiHanh:
                dt = datetime.strptime(f"{t.ngayKhoiHanh} {t.gioKhoiHanh}", "%Y-%m-%d %H:%M")
        except Exception:
            dt = None

        is_past = bool(dt and dt < now)
        if is_past:
            continue

        items.append({
            "trip_id": t.maChuyen,
            "date": t.ngayKhoiHanh,
            "time": t.gioKhoiHanh,
            "direction": normalize_direction(getattr(t, "huong", None)),
            "dt": dt.isoformat() if dt else None,
            "detail_url": url_for("trip_detail", trip_id=t.maChuyen),
        })

    items.sort(key=lambda x: (0 if x["dt"] else 1, x["dt"] or "9999", x["trip_id"]))
    items = items[:limit]

    return jsonify({
        "ok": True,
        "route_id": tuyen_id,
        "count": len(items),
        "items": items,
    })


@app.route("/api/routes/<int:tuyen_id>/stop_offsets")
def api_route_stop_offsets(tuyen_id):
    tuyen = TuyenXe.query.get_or_404(tuyen_id)
    dir_ = normalize_direction(request.args.get("dir") or "DI")

    data = get_stop_offsets(tuyen, dir_)
    if not data.get("ok"):
        return jsonify({"ok": False, "error": data.get("error") or "Không tính được offset trạm."}), 400

    offsets = data.get("offsets") or {}
    dist_m = data.get("dist_m") or {}

    items = []
    for s in data.get("items") or []:
        items.append({
            "stop_id": s.maTram,
            "order": s.thuTuTrenTuyen,
            "name": s.tenTram,
            "address": s.diaChi,
            "lat": float(s.lat) if s.lat is not None else None,
            "lng": float(s.lng) if s.lng is not None else None,
            "offset_s": float(offsets.get(s.maTram)) if offsets.get(s.maTram) is not None else None,
            "distance_m": float(dist_m.get(s.maTram)) if dist_m.get(s.maTram) is not None else None,
        })

    return jsonify({
        "ok": True,
        "route_id": tuyen.maTuyen,
        "route_code": tuyen.maHienThi,
        "direction": dir_,
        "source": data.get("source"),
        "items": items,
    })


@app.route("/api/routes/<int:tuyen_id>/stop_etas")
def api_route_stop_etas(tuyen_id):
    tuyen = TuyenXe.query.get_or_404(tuyen_id)
    dir_ = normalize_direction(request.args.get("dir") or "DI")

    at_raw = (request.args.get("at") or "").strip()
    at = None
    if at_raw:
        try:
            at = datetime.fromisoformat(at_raw)
        except Exception:
            at = None

    data = compute_next_stop_etas(tuyen, dir_, at=at)
    if not data.get("ok"):
        return jsonify(data), 400
    return jsonify(data)


@app.route("/api/cards/validate", methods=["POST"])
def api_validate_card():
    # Demo soát thẻ tháng/quý/năm khi lên xe.
    user = current_user()
    if not user or user.vai_tro != "ADMIN":
        return jsonify({"ok": False, "error": "Bạn không có quyền truy cập."}), 403

    data = request.get_json(silent=True) or {}
    code = (data.get("code") or data.get("maSoThe") or "").strip().upper()
    if not code:
        return jsonify({"ok": False, "error": "Thiếu mã thẻ (code)."}), 400

    card = TheTu.query.filter(func.upper(TheTu.maSoThe) == code).first()
    if not card:
        return jsonify({"ok": False, "error": "Không tìm thấy thẻ."}), 404

    today = datetime.utcnow().date()

    def _parse_date(s):
        try:
            return datetime.strptime(str(s), "%Y-%m-%d").date()
        except Exception:
            return None

    start = _parse_date(card.ngayBatDau) or today
    end = _parse_date(card.ngayHetHan) or today

    status = (card.trangThai or "").upper()
    paid = (card.payment_status or "").upper() == "DA_THANH_TOAN"
    active = status == "KICH_HOAT" and paid and (start <= today <= end)

    return jsonify({
        "ok": True,
        "valid": bool(active),
        "status": status,
        "paid": bool(paid),
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "card_id": card.maThe,
        "card_code": card.maSoThe,
        "customer_id": card.khach_hang_id,
    })


@app.route("/api/routes/<int:tuyen_id>/stops_geo")
def api_route_stops_geo(tuyen_id):
    tuyen = TuyenXe.query.get_or_404(tuyen_id)

    dir_ = (request.args.get("dir") or "DI").strip().upper()
    stops = _query_stops_by_direction(tuyen, dir_).all()

    return jsonify(build_stops_geo(stops, route_code=tuyen.maHienThi))
# ==================== MAIN ====================

if __name__ == "__main__":
    # Dev server (đừng dùng cho production). Khi deploy hãy dùng gunicorn/WSGI.
    debug = os.getenv("FLASK_DEBUG", "1").strip() == "1"
    app.run(debug=debug)
