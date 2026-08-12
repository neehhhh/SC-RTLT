Option Explicit
Dim shell, fso, launcher
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
launcher = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\SCRTLTPublic\SC-RTLT_Public.vbs")
If Not fso.FileExists(launcher) Then
    MsgBox "SC-RTLT Public n'est pas encore installe. Lance d'abord Setup.bat.", 48, "SC-RTLT Public"
    WScript.Quit 1
End If
shell.Run "wscript.exe """ & launcher & """", 0, False
