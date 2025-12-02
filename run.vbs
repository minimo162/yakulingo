' ============================================================
' YakuLingo Silent Launcher
' Launches YakuLingo without showing a console window
' - Shows startup notification for user feedback
' - Prevents multiple instances
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

' Check if app is already running (port 8765 in use)
If IsPortInUse(8765) Then
    ' App is already running - try to bring it to foreground
    MsgBox "YakuLingo is already running.", vbInformation, "YakuLingo"
    WScript.Quit 0
End If

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

' Show startup notification (non-blocking balloon tip)
ShowStartupNotification

' Launch app silently using pythonw.exe (no console)
objShell.CurrentDirectory = scriptDir
objShell.Run """" & pythonExe & """ """ & appScript & """", 0, False

WScript.Quit 0

' ============================================================
' Helper Functions
' ============================================================

Function IsPortInUse(port)
    ' Check if a port is in use by trying netstat
    Dim result, output
    On Error Resume Next

    ' Use PowerShell to check port (faster than netstat parsing)
    result = objShell.Run("powershell -WindowStyle Hidden -Command ""exit ([bool](Get-NetTCPConnection -LocalPort " & port & " -ErrorAction SilentlyContinue))""", 0, True)

    ' Exit code 1 = port in use, 0 = port free
    If result = 1 Then
        IsPortInUse = True
    Else
        IsPortInUse = False
    End If

    On Error GoTo 0
End Function

Sub ShowStartupNotification()
    ' Show a Windows balloon notification that the app is starting
    ' This provides immediate visual feedback to the user
    On Error Resume Next

    Dim scriptPath, ps_command

    ' Use PowerShell to show a toast notification (Windows 10+)
    ps_command = "powershell -WindowStyle Hidden -Command """ & _
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; " & _
        "$template = [Windows.UI.Notifications.ToastTemplateType]::ToastText01; " & _
        "$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template); " & _
        "$xml.GetElementsByTagName('text')[0].AppendChild($xml.CreateTextNode('Starting YakuLingo...')) | Out-Null; " & _
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); " & _
        "$toast.ExpirationTime = [DateTimeOffset]::Now.AddSeconds(3); " & _
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('YakuLingo').Show($toast)" & _
        """"

    ' Run notification asynchronously (don't wait)
    objShell.Run ps_command, 0, False

    On Error GoTo 0
End Sub
