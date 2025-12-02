' ============================================================
' YakuLingo Silent Launcher
' Launches YakuLingo without showing a console window
' ============================================================

Option Explicit

Dim objShell, objFSO, scriptDir, pythonExe, appScript
Dim venvDir, uvPythonDir, pythonDir, folder
Dim pyvenvCfg, cfgContent, newCfgContent, line, version
Dim objFile, homeFound

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

' Get script directory
scriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)

' Set paths
venvDir = scriptDir & "\.venv"
uvPythonDir = scriptDir & "\.uv-python"
appScript = scriptDir & "\app.py"

' Find Python directory in .uv-python (cpython-*)
pythonDir = ""
If objFSO.FolderExists(uvPythonDir) Then
    For Each folder In objFSO.GetFolder(uvPythonDir).SubFolders
        If Left(folder.Name, 8) = "cpython-" Then
            pythonDir = folder.Path
            Exit For
        End If
    Next
End If

If pythonDir = "" Then
    MsgBox "Python not found in .uv-python directory." & vbCrLf & vbCrLf & _
           "Please reinstall the application.", _
           vbCritical, "YakuLingo - Error"
    WScript.Quit 1
End If

' Check venv exists
pythonExe = venvDir & "\Scripts\pythonw.exe"
If Not objFSO.FileExists(pythonExe) Then
    MsgBox ".venv not found." & vbCrLf & vbCrLf & _
           "Please reinstall the application.", _
           vbCritical, "YakuLingo - Error"
    WScript.Quit 1
End If

' Fix pyvenv.cfg home path for portability
pyvenvCfg = venvDir & "\pyvenv.cfg"
If objFSO.FileExists(pyvenvCfg) Then
    ' Read existing config to get version
    version = ""
    Set objFile = objFSO.OpenTextFile(pyvenvCfg, 1)
    Do While Not objFile.AtEndOfStream
        line = objFile.ReadLine
        If Left(LCase(line), 7) = "version" Then
            version = line
        End If
    Loop
    objFile.Close

    ' Write new config with correct home path
    Set objFile = objFSO.CreateTextFile(pyvenvCfg, True)
    objFile.WriteLine "home = " & pythonDir
    objFile.WriteLine "include-system-site-packages = false"
    If version <> "" Then
        objFile.WriteLine version
    End If
    objFile.Close
End If

' Set environment variables
Dim env
Set env = objShell.Environment("Process")
env("VIRTUAL_ENV") = venvDir
env("PLAYWRIGHT_BROWSERS_PATH") = scriptDir & "\.playwright-browsers"
env("PATH") = venvDir & "\Scripts;" & pythonDir & ";" & pythonDir & "\Scripts;" & env("PATH")

' Launch app silently using pythonw.exe (no console)
objShell.CurrentDirectory = scriptDir
objShell.Run """" & pythonExe & """ """ & appScript & """", 0, False

WScript.Quit 0
