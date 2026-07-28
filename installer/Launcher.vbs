Option Explicit
Dim shell, fso, launcher
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
launcher = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\PublicRealTimeChecker\Public_Real_Time_Checker.vbs")
If Not fso.FileExists(launcher) Then
    MsgBox "Public Real Time Checker n'est pas encore installe. Lance d'abord Setup.bat.", 48, "Public Real Time Checker"
    WScript.Quit 1
End If
shell.Run "wscript.exe """ & launcher & """", 0, False
