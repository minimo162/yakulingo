' ============================================================
' YakuLingo One-Click Setup (GUI Version)
' Double-click this file to set up YakuLingo
' ============================================================

Option Explicit

On Error Resume Next

Dim objShell, objFSO, scriptDir, psScript, psScriptToRun

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

' Handle Japanese (non-ASCII) characters in path
' PowerShell's -File parameter has issues with non-ASCII paths
' Solution: Use ShortPath (8.3 format) or copy to TEMP if ShortPath unavailable
Dim psScriptFile, shortPath, tempDir, tempScript, needsCopy
Set psScriptFile = objFSO.GetFile(psScript)
shortPath = psScriptFile.ShortPath
needsCopy = False

' Check if ShortPath is different from original (8.3 is enabled)
' Also check if path contains non-ASCII characters
If shortPath = psScript Then
    ' ShortPath is same as original - 8.3 may be disabled or path has non-ASCII
    ' Check for non-ASCII characters in path
    Dim i, charCode
    For i = 1 To Len(psScript)
        charCode = AscW(Mid(psScript, i, 1))
        If charCode > 127 Then
            needsCopy = True
            Exit For
        End If
    Next
End If

' Determine which script path to use
If needsCopy Then
    ' Copy script to TEMP directory (always ASCII path)
    On Error Resume Next
    tempDir = objShell.Environment("Process")("TEMP") & "\YakuLingo_Setup"
    If Not objFSO.FolderExists(tempDir) Then
        objFSO.CreateFolder(tempDir)
    End If
    tempScript = tempDir & "\setup.ps1"
    objFSO.CopyFile psScript, tempScript, True
    If Err.Number <> 0 Then
        On Error GoTo 0
        MsgBox "Failed to copy setup script to TEMP folder." & vbCrLf & vbCrLf & _
               "Error: " & Err.Description, _
               vbCritical, "YakuLingo Setup - Error"
        WScript.Quit 1
    End If
    On Error GoTo 0
    psScriptToRun = tempScript
Else
    ' Use ShortPath if available, otherwise original path
    psScriptToRun = shortPath
End If

' Run PowerShell script with GUI mode (hidden console)
Dim command, exitCode
' If script was copied to TEMP, write original ShareDir to file (Unicode safe)
If needsCopy Then
    ' Write ShareDir to file using UTF-16 LE (native Windows Unicode, no BOM issues)
    Dim shareDirFile, shareDirTS
    shareDirFile = tempDir & "\share_dir.txt"
    Set shareDirTS = objFSO.CreateTextFile(shareDirFile, True, True) ' True = Unicode (UTF-16 LE)
    shareDirTS.Write scriptDir
    shareDirTS.Close
    Set shareDirTS = Nothing
End If
' Run PowerShell via cmd.exe (stderr redirect removed - debug log captures errors)
command = "cmd.exe /c powershell.exe -ExecutionPolicy Bypass -File """ & psScriptToRun & """ -GuiMode"

' Run and wait for completion (0 = hidden, True = wait)
exitCode = objShell.Run(command, 0, True)

If exitCode <> 0 Then
    Dim errorMessage, debugLogPath
    debugLogPath = objShell.Environment("Process")("TEMP") & "\YakuLingo_setup_debug.log"
    errorMessage = "Setup failed." & vbCrLf & vbCrLf & _
                   "Error code: " & exitCode & vbCrLf & vbCrLf & _
                   "Details: " & debugLogPath

    MsgBox errorMessage, vbCritical, "YakuLingo Setup - Error"
    WScript.Quit exitCode
End If

' Success message is shown by PowerShell script in GUI mode
WScript.Quit 0
