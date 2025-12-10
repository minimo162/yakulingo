' ============================================================
' YakuLingo One-Click Setup (GUI Version)
' Double-click this file to set up YakuLingo
' ============================================================

Option Explicit

Dim objShell, objFSO, scriptDir, psScript

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

' Get script directory
scriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
psScript = scriptDir & "\.scripts\setup.ps1"

' Check if PowerShell script exists
If Not objFSO.FileExists(psScript) Then
    MsgBox "Setup script not found." & vbCrLf & vbCrLf & _
           "Please ensure .scripts\setup.ps1 exists.", _
           vbCritical, "YakuLingo Setup - Error"
    WScript.Quit 1
End If

' Run PowerShell script with GUI mode (hidden console)
Dim command, exitCode, errorLog, wshShellEnv
Set wshShellEnv = objShell.Environment("Process")
' Use local TEMP for error log (network share may be read-only)
errorLog = wshShellEnv("TEMP") & "\YakuLingo_setup_error.log"

' Delete previous error log if exists (ignore errors - may be on read-only share)
On Error Resume Next
If objFSO.FileExists(errorLog) Then
    objFSO.DeleteFile errorLog, True
End If
On Error GoTo 0

' Run PowerShell with error output redirected to log file (UTF-8)
command = "cmd.exe /c chcp 65001 >nul && powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & psScript & """ -GuiMode 2>""" & errorLog & """"

' Run and wait for completion (0 = hidden window, True = wait)
exitCode = objShell.Run(command, 0, True)

If exitCode <> 0 Then
    Dim errorMessage
    errorMessage = "Setup failed." & vbCrLf & vbCrLf & "Error code: " & exitCode

    ' Try to read error log for more details (UTF-8)
    On Error Resume Next
    If objFSO.FileExists(errorLog) Then
        ' Check file size first (empty file causes ADODB.Stream errors)
        If objFSO.GetFile(errorLog).Size > 0 Then
            Dim objStream, errorContent
            Set objStream = CreateObject("ADODB.Stream")
            objStream.Type = 2 ' adTypeText
            objStream.Charset = "UTF-8"
            objStream.Open
            objStream.LoadFromFile errorLog
            If Err.Number = 0 Then
                errorContent = objStream.ReadText()
                If Len(errorContent) > 0 Then
                    errorMessage = errorMessage & vbCrLf & vbCrLf & "Details:" & vbCrLf & errorContent
                End If
            End If
            objStream.Close
            Set objStream = Nothing
        End If
    End If
    On Error GoTo 0

    MsgBox errorMessage, vbCritical, "YakuLingo Setup - Error"
    WScript.Quit exitCode
End If

' Success message is shown by PowerShell script in GUI mode
WScript.Quit 0
