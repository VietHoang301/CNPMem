import os
from werkzeug.security import generate_password_hash
from app import app, db, TaiKhoan

def seed_admin():
    """
    Tạo tài khoản ADMIN mặc định nếu chưa tồn tại trong bảng tai_khoan.
    Thông tin mặc định:
      - Email: admin@smartbus.local
      - Mật khẩu: admin123
    """
    with app.app_context():
        # Đảm bảo bảng đã được tạo
        db.create_all()
        
        # 1. Cấu hình thông tin Admin (có thể lấy từ biến môi trường hoặc dùng mặc định)
        admin_email = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@smartbus.local")
        admin_password = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
        
        # 2. Kiểm tra xem tài khoản admin đã tồn tại chưa
        # Lưu ý: Trong app.py, model là TaiKhoan, cột phân quyền là 'vai_tro'
        existing_admin = TaiKhoan.query.filter_by(email=admin_email).first()
        
        if not existing_admin:
            print(f"--- Đang tạo tài khoản Admin ({admin_email}) ---")
            
            new_admin = TaiKhoan(
                email=admin_email,
                mat_khau_hash=generate_password_hash(admin_password),
                vai_tro="ADMIN",       # Theo logic trong app.py
                trangThai="HOAT_DONG"  # Theo logic trong app.py
            )
            
            db.session.add(new_admin)
            try:
                db.session.commit()
                print(f"✅ Đã tạo xong Admin: {admin_email} / Pass: {admin_password}")
            except Exception as e:
                db.session.rollback()
                print(f"❌ Lỗi khi tạo Admin: {str(e)}")
        else:
            # Nếu đã có user với email này, kiểm tra xem có phải ADMIN không để cập nhật
            if existing_admin.vai_tro != "ADMIN":
                print(f"⚠️ Tài khoản {admin_email} đã tồn tại nhưng không phải ADMIN. Đang cập nhật quyền...")
                existing_admin.vai_tro = "ADMIN"
                db.session.commit()
                print("✅ Đã cập nhật quyền ADMIN.")
            else:
                print(f"ℹ️ Tài khoản Admin {admin_email} đã tồn tại.")

if __name__ == "__main__":
    seed_admin()
