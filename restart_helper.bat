@echo off
REM ==========================================================================
REM  Được /api/restart gọi để khởi động lại server. KHONG chay truc tiep.
REM
REM  Vi sao can file rieng thay vi truyen lenh long nhau vao cmd /c:
REM  subprocess.list2cmdline escape dau ngoac theo quy uoc MSVC (\") ma cmd.exe
REM  khong hieu, nen lenh long nhau im lang khong chay gi ca. Da do bang thuc
REM  nghiem: bien the inline that bai, bien the co file helper chay dung.
REM
REM  Vi sao dung `start` thay vi goi start.bat truc tiep:
REM  start.bat co buoc `taskkill /PID <server> /F /T` — /T kill ca CAY con theo
REM  PPID. Neu start.bat la con cua server cu thi no tu kill chinh minh. `start`
REM  tao process moi; cmd nay thoat ngay sau do, nen cha cua start.bat la mot PID
REM  da chet => khong con nam trong cay cua server cu.
REM
REM  Delay 2s de response HTTP cua /api/restart kip bay ve browser truoc khi
REM  start.bat kill process dang phuc vu.
REM ==========================================================================
cd /d "%~dp0"
timeout /t 2 /nobreak >nul
start "" "%~dp0start.bat"
