' ============================================================
' YakuLingo One-Click Setup (GUI Version)
' Double-click this file to install YakuLingo
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
Dim command, exitCode
command = "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & psScript & """ -GuiMode"

' Run and wait for completion (0 = hidden window, True = wait)
exitCode = objShell.Run(command, 0, True)

If exitCode <> 0 Then
    MsgBox "Setup failed." & vbCrLf & vbCrLf & _
           "Error code: " & exitCode & vbCrLf & _
           "Please contact your administrator.", _
           vbCritical, "YakuLingo Setup - Error"
    WScript.Quit exitCode
End If

' Success message is shown by PowerShell script in GUI mode
WScript.Quit 0
