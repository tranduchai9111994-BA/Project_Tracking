#!/bin/bash
echo "============================================"
echo "  iHRP Function List Tracker"
echo "  Dashboard theo dõi tiến độ dự án"
echo "============================================"
echo ""

# Kiểm tra Python
if ! command -v python3 &> /dev/null; then
    echo "[LỖI] Không tìm thấy Python3."
    exit 1
fi

# Tạo venv nếu chưa có
if [ ! -d "venv" ]; then
    echo "[1/3] Đang tạo môi trường ảo..."
    python3 -m venv venv
fi

# Kích hoạt venv và cài dependencies
echo "[2/3] Đang cài đặt thư viện..."
source venv/bin/activate
pip install -r requirements.txt -q

# Tạo thư mục uploads
mkdir -p uploads

# Chạy app
echo "[3/3] Đang khởi động server..."
echo ""
echo "============================================"
echo "  Mở trình duyệt tại: http://localhost:5000"
echo "  Nhấn Ctrl+C để dừng server"
echo "============================================"
echo ""

# Tự động mở trình duyệt
if [[ "$OSTYPE" == "darwin"* ]]; then
    open http://localhost:5000 &
else
    xdg-open http://localhost:5000 2>/dev/null &
fi

python3 app.py
