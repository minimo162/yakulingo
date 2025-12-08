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
Dim command, exitCode, errorLog
errorLog = scriptDir & "\.scripts\setup_error.log"

' Delete previous error log if exists
If objFSO.FileExists(errorLog) Then
    objFSO.DeleteFile errorLog, True
End If

' Run PowerShell with error output redirected to log file
command = "cmd.exe /c powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & psScript & """ -GuiMode 2>""" & errorLog & """"

' Run and wait for completion (0 = hidden window, True = wait)
exitCode = objShell.Run(command, 0, True)

If exitCode <> 0 Then
    Dim errorMessage
    errorMessage = "Setup failed." & vbCrLf & vbCrLf & "Error code: " & exitCode

    ' Try to read error log for more details
    If objFSO.FileExists(errorLog) Then
        Dim errorFile, errorContent
        Set errorFile = objFSO.OpenTextFile(errorLog, 1, False, -1)
        If Not errorFile.AtEndOfStream Then
            errorContent = errorFile.ReadAll()
            If Len(errorContent) > 0 Then
                errorMessage = errorMessage & vbCrLf & vbCrLf & "Details:" & vbCrLf & errorContent
            End If
        End If
        errorFile.Close
    End If

    MsgBox errorMessage, vbCritical, "YakuLingo Setup - Error"
    WScript.Quit exitCode
End If

' Success message is shown by PowerShell script in GUI mode
WScript.Quit 0
