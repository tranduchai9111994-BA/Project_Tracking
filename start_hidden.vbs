' Launcher an nap cho iHRP Tracker — chay start.bat hoan toan an (khong hien
' cua so, khong o taskbar), mo trinh duyet vao trang dashboard nhu binh thuong.
' Neu server khong len duoc: chay truc tiep start.bat (double-click file .bat)
' de xem log loi chi tiet.
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = scriptDir
shell.Run """" & scriptDir & "\start.bat""", 0, False
