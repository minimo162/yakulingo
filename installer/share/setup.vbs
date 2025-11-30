' ============================================================
' YakuLingo One-Click Setup (GUI Version)
' Double-click this file to install YakuLingo
' ============================================================

Option Explicit

Dim objShell, objFSO, scriptDir, psScript, result

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

' Confirmation dialog
result = MsgBox("YakuLingo Setup" & vbCrLf & vbCrLf & _
                "This will install YakuLingo on your computer:" & vbCrLf & _
                "  - Copy files to local storage" & vbCrLf & _
                "  - Create desktop shortcut" & vbCrLf & vbCrLf & _
                "Continue?", _
                vbYesNo + vbQuestion, "YakuLingo Setup")

If result <> vbYes Then
    WScript.Quit 0
End If

' Run PowerShell script with GUI mode (hidden console)
' The -File parameter passes the script path
' ErrorLevel is captured via objShell.Run return value
Dim command, exitCode
command = "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & psScript & """ -GuiMode"

' Run and wait for completion (1 = activate window, True = wait)
' Using 0 instead of 1 to keep it hidden
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
