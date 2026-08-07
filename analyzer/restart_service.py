"""
Restart server từ dashboard — giao việc cho launcher, không tự restart chính mình.

Vì sao không dùng `os.execv` hay tự spawn `python app.py`: process này đang giữ
socket lắng nghe port 5000. `os.execv` thay ảnh process nhưng handle/thread của
Werkzeug thì không được dọn sạch, còn tự spawn thì process mới không bind được
port cho tới khi process cũ nhả — một cuộc đua không đáng chơi. `start.bat` **đã
có sẵn** bước dọn process chiếm port, kèm cả venv và cài dependency, nên nó là
nơi đúng để làm việc này.

Bốn cái bẫy đã phải thiết kế vòng qua:

1. `taskkill /PID <pid> /F /T` trong start.bat kill cả **cây con** theo PPID. Nếu
   spawn start.bat làm con trực tiếp thì nó tự kill luôn chính mình. Nên phải qua
   hai chặng: `restart_helper.bat` dùng lệnh `start` để tạo process mới rồi thoát
   ngay. Cha của start.bat khi đó là một PID đã chết, không còn nằm trong cây của
   ta nữa.

2. **Không truyền lệnh lồng nhau vào `cmd /c`.** `subprocess.list2cmdline` escape
   dấu ngoặc theo quy ước MSVC (`\"`) mà `cmd.exe` không hiểu, nên lệnh im lặng
   không chạy gì — không lỗi, không log, `Popen` vẫn báo thành công. Đã đo bằng
   thực nghiệm: biến thể inline thất bại, biến thể có file helper chạy đúng. Vì
   vậy toàn bộ phần script nằm trong `restart_helper.bat`, argv không có quote lồng.

3. Nếu process con **thừa hưởng socket lắng nghe**, port vẫn bị giữ sau khi ta
   chết và server mới không bind được. `subprocess` mặc định `close_fds=True`
   (bInheritHandles=FALSE) nên không thừa hưởng — chỉ cần đừng tự tay tắt nó.

4. start.bat mở browser ở cuối. Restart từ dashboard thì người dùng **đã có tab**,
   mở thêm tab mới mỗi lần restart rất phiền → truyền `IHRP_NO_BROWSER=1`.

Chủ ý **không** tự thoát process: start.bat kiểm tra Python **trước** bước kill,
nên nếu môi trường lỗi nó sẽ dừng lại và báo mà ta vẫn còn sống để phục vụ. Tự
thoát trước sẽ đổi một lỗi hiển thị được thành cảnh không còn server nào cả.
"""
from __future__ import annotations

import os
import subprocess
import sys

LAUNCHER_WINDOWS = "start.bat"
HELPER_WINDOWS = "restart_helper.bat"

# Delay nằm trong restart_helper.bat — đủ để response HTTP kịp flush về browser
# trước khi start.bat kill process này.
_KILL_DELAY_SEC = 2


class RestartUnsupported(RuntimeError):
    """Nền tảng hoặc cấu hình không cho phép restart tự động."""


def can_restart(root: str) -> tuple[bool, str]:
    """Kiểm điều kiện trước, để UI ẩn/disable nút thay vì để người dùng bấm rồi lỗi."""
    if os.name != "nt":
        return False, (
            "Restart tự động chỉ hỗ trợ Windows. start.sh không dọn process đang "
            "giữ port nên server mới sẽ không bind được — hãy tắt và chạy lại "
            "./start.sh bằng tay."
        )
    for name in (LAUNCHER_WINDOWS, HELPER_WINDOWS):
        if not os.path.isfile(os.path.join(root, name)):
            return False, f"Không tìm thấy {name} trong {root}."
    return True, ""


def spawn_restart(root: str) -> dict:
    """
    Nhờ launcher khởi động lại server. Trả về ngay, không chờ.

    Process này sẽ bị start.bat kill sau ~2 giây. Frontend phải coi việc mất kết
    nối sau khi gọi hàm này là **bình thường**, và poll `/api/build-info` tới khi
    `started_at` đổi.
    """
    ok, reason = can_restart(root)
    if not ok:
        raise RestartUnsupported(reason)

    env = dict(os.environ)
    env["IHRP_NO_BROWSER"] = "1"
    # Đánh dấu instance do dashboard khởi chạy: lần restart sau sẽ taskkill nó,
    # start.bat khi đó phải tự đóng thay vì treo ở `pause` kèm thông báo "[LOI]"
    # sai lệch. Biến này truyền tiếp qua các lần restart nối nhau.
    env["IHRP_RESTART"] = "1"

    # argv phẳng, không quote lồng — xem bẫy số 2 ở docstring module.
    argv = ["cmd", "/c", HELPER_WINDOWS]
    base_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)

    def _spawn(flags: int):
        return subprocess.Popen(
            argv,
            cwd=root,
            env=env,
            close_fds=True,  # không để con thừa hưởng socket đang lắng nghe
            creationflags=flags,
        )

    # Thoát Job Object nếu process này đang nằm trong một job: khi job bị đóng,
    # Windows kill **mọi hậu duệ** bất kể PPID, nên server vừa khởi động lại sẽ
    # chết theo. Đã gặp thật khi chạy app từ terminal có bọc job. Không phải job
    # nào cũng cho breakaway, nên thất bại thì quay về cách thường.
    try:
        proc = _spawn(base_flags | breakaway)
        used_breakaway = True
    except OSError:
        proc = _spawn(base_flags)
        used_breakaway = False

    return {
        "breakaway": used_breakaway,
        "spawned": True,
        "delay_sec": _KILL_DELAY_SEC,
        "helper": HELPER_WINDOWS,
        "launcher": LAUNCHER_WINDOWS,
        "helper_pid": proc.pid,
        "pid_current": os.getpid(),
        "python_current": sys.executable,
    }
