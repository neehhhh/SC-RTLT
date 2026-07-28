Option Explicit
Dim shell, fso, folder, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
command = "cmd.exe /c """ & folder & "\Public_Real_Time_Checker.cmd"""
shell.Run command, 0, False
