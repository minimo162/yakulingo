Option Explicit
'
' ECM_CA1 ? Simple Panel v3.4e (JA→EN Translator with CSV Dictionary, Shapes support + robust CSV parser)
' - 変更点（v3.4e）:
'
' - 既存（v3.4d）:
'   * 【Fix】CsvFields を PushField 方式で安全化（fields[count] 問題の根治）。
'   * 図形（テキストボックス等）もプレビュー/翻訳の対象。
'   * プレビュー再実行時、ListObject/フィルタを完全初期化。
'   * 処理範囲を 1000 行 × 1000 列に固定化。
'   * CSVは毎回読み込み（キャッシュなし）。失敗時は空Collectionを返す。

' ===== UI定義 =====
Private Const HELPER_SHEET As String = "ECM_Helper"
Private Const COL_WB_PATH As String = "B5"
Private Const COL_CSV_PATH As String = "B9"
Private Const CELL_STATUS  As String = "B16"
Private Const COPILOT_DIAG_START_ROW As Long = 19
Private Const COPILOT_DIAG_MAX_LINES As Long = 200

' 範囲開始（A1）
Private Const RANGE_START_ROW As Long = 1
Private Const RANGE_START_COL As Long = 1
Private Const TRANSLATION_MAX_ROWS As Long = 1000
Private Const TRANSLATION_MAX_COLS As Long = 1000

' 配色
Private Const COLOR_PRIMARY       As Long = &HE5464F
Private Const COLOR_PRIMARY_LIGHT As Long = &HFFF2EE
Private Const COLOR_BORDER        As Long = &HCA383F
Private Const COLOR_TEXT          As Long = &H1A1A1A
Private Const COLOR_BUTTON_BG     As Long = &HF5F5F5

' フォント
Private Const UI_FONT As String = "Segoe UI"
Private Const ALT_FONT As String = "Calibri"

' HTTP セキュアプロトコル (WinHTTP 用)
Private Const SECURE_PROTOCOL_TLS1   As Long = &H80
Private Const SECURE_PROTOCOL_TLS1_1 As Long = &H200
Private Const SECURE_PROTOCOL_TLS1_2 As Long = &H800
Private Const MIN_IPHLPAPI_VERSION_FOR_NETSH As String = "10.0.16299.0"

' 絵文字
Private Const USE_EMOJI As Boolean = True

' マッチング正規化
Private Const IGNORE_ALL_SPACES_WHEN_MATCHING As Boolean = True
Private Const NORMALIZE_WIDE_NARROW           As Boolean = True
Private Const SHAPE_BOUNDS_EPSILON            As Double = 0.5

' グローバル（互換のため残置）
Private g_entries As Collection
Private g_loadedDictPath As String
Private g_dictMtime As Date
Private g_dictSize As Double
Private g_dictHash As String
Private g_lastCsvError As String
Private g_lastCsvStage As String
Private g_copilotDriver As Object
Private g_lastCopilotDiagPort As Long
' === EdgeDriver 自前サービス管理 ===
Private g_edgeSvcExec  As Object
Private g_edgeSvcPid   As Long
Private g_edgeSvcPort  As Long
Private g_edgeSvcUrl   As String

#If VBA7 Then
Private Declare PtrSafe Function MultiByteToWideChar Lib "kernel32" _
  (ByVal codePage As Long, ByVal dwFlags As Long, ByVal lpMultiByteStr As LongPtr, _
   ByVal cbMultiByte As Long, ByVal lpWideCharStr As LongPtr, ByVal cchWideChar As Long) As Long
#If Win64 Then
Private Declare PtrSafe Function OpenClipboard Lib "user32" (ByVal hwnd As LongPtr) As Long
Private Declare PtrSafe Function CloseClipboard Lib "user32" () As Long
Private Declare PtrSafe Function EmptyClipboard Lib "user32" () As Long
Private Declare PtrSafe Function SetClipboardData Lib "user32" (ByVal wFormat As Long, ByVal hMem As LongPtr) As LongPtr
Private Declare PtrSafe Function GlobalAlloc Lib "kernel32" (ByVal uFlags As Long, ByVal dwBytes As LongPtr) As LongPtr
Private Declare PtrSafe Function GlobalLock Lib "kernel32" (ByVal hMem As LongPtr) As LongPtr
Private Declare PtrSafe Function GlobalUnlock Lib "kernel32" (ByVal hMem As LongPtr) As Long
Private Declare PtrSafe Function GlobalFree Lib "kernel32" (ByVal hMem As LongPtr) As LongPtr
Private Declare PtrSafe Sub CopyMemory Lib "kernel32" Alias "RtlMoveMemory" (ByVal Destination As LongPtr, ByVal Source As LongPtr, ByVal Length As LongPtr)
#Else
Private Declare PtrSafe Function OpenClipboard Lib "user32" (ByVal hwnd As LongPtr) As Long
Private Declare PtrSafe Function CloseClipboard Lib "user32" () As Long
Private Declare PtrSafe Function EmptyClipboard Lib "user32" () As Long
Private Declare PtrSafe Function SetClipboardData Lib "user32" (ByVal wFormat As Long, ByVal hMem As LongPtr) As LongPtr
Private Declare PtrSafe Function GlobalAlloc Lib "kernel32" (ByVal uFlags As Long, ByVal dwBytes As LongPtr) As LongPtr
Private Declare PtrSafe Function GlobalLock Lib "kernel32" (ByVal hMem As LongPtr) As LongPtr
Private Declare PtrSafe Function GlobalUnlock Lib "kernel32" (ByVal hMem As LongPtr) As Long
Private Declare PtrSafe Function GlobalFree Lib "kernel32" (ByVal hMem As LongPtr) As LongPtr
Private Declare PtrSafe Sub CopyMemory Lib "kernel32" Alias "RtlMoveMemory" (ByVal Destination As LongPtr, ByVal Source As LongPtr, ByVal Length As LongPtr)
#End If
#Else
Private Declare Function MultiByteToWideChar Lib "kernel32" _
  (ByVal codePage As Long, ByVal dwFlags As Long, ByVal lpMultiByteStr As Long, _
   ByVal cbMultiByte As Long, ByVal lpWideCharStr As Long, ByVal cchWideChar As Long) As Long
Private Declare Function OpenClipboard Lib "user32" (ByVal hwnd As Long) As Long
Private Declare Function CloseClipboard Lib "user32" () As Long
Private Declare Function EmptyClipboard Lib "user32" () As Long
Private Declare Function SetClipboardData Lib "user32" (ByVal wFormat As Long, ByVal hMem As Long) As Long
Private Declare Function GlobalAlloc Lib "kernel32" (ByVal uFlags As Long, ByVal dwBytes As Long) As Long
Private Declare Function GlobalLock Lib "kernel32" (ByVal hMem As Long) As Long
Private Declare Function GlobalUnlock Lib "kernel32" (ByVal hMem As Long) As Long
Private Declare Function GlobalFree Lib "kernel32" (ByVal hMem As Long) As Long
Private Declare Sub CopyMemory Lib "kernel32" Alias "RtlMoveMemory" (ByVal Destination As Long, ByVal Source As Long, ByVal Length As Long)
#End If

Private Const CP_UTF8 As Long = 65001
Private Const CP_SHIFT_JIS As Long = 932
Private Const CP_ACP As Long = 0

Private Const CF_UNICODETEXT As Long = 13
Private Const GMEM_MOVEABLE As Long = &H2
Private Const GMEM_ZEROINIT As Long = &H40

'========================
'          UI
'========================
Public Sub ECM_Setup()
  Application.ScreenUpdating = False
  Application.DisplayAlerts = False

  Dim ws As Worksheet
  Set ws = GetOrCreatePanel(HELPER_SHEET)
  ws.Cells.Clear

  With ws.Range("A1")
    .value = LabelWithIcon("globe", "ECM Translator")
    .Font.Bold = True
    .Font.size = 18
    .Font.Color = COLOR_TEXT
    On Error Resume Next
    .Font.Name = IIf(USE_EMOJI, "Segoe UI Emoji", UI_FONT)
    If .Font.Name <> "Segoe UI Emoji" And USE_EMOJI Then .Font.Name = "Segoe UI Symbol"
    If .Font.Name <> "Segoe UI Emoji" And .Font.Name <> "Segoe UI Symbol" Then .Font.Name = ALT_FONT
    On Error GoTo 0
  End With
  ws.Range("A1:F1").Interior.Color = COLOR_PRIMARY_LIGHT

  ws.Range("A2").value = "翻訳対象のブックと辞書CSVを指定し、「辞書翻訳」または「copilot翻訳」を実行してください。"
  ws.Range("A2:F2").Merge
  ws.Range("A2:F2").Interior.Color = COLOR_PRIMARY_LIGHT
  ws.Range("A2").Font.Color = COLOR_TEXT
  ws.Range("A2").Font.size = 11

  ws.Range("A4").value = "ターゲットブック"
  ws.Range("A4").Font.Bold = True
  ws.Range("B5:F5").Merge
  With ws.Range(COL_WB_PATH)
    .value = ThisWorkbook.fullName
    .HorizontalAlignment = xlLeft
    .VerticalAlignment = xlTop
    .WrapText = True
  End With

  ws.Range("A8").value = "辞書CSV"
  ws.Range("A8").Font.Bold = True
  ws.Range("B9:F9").Merge
  With ws.Range(COL_CSV_PATH)
    .value = ThisWorkbook.path & Application.PathSeparator & "ECM_JE_Dictionary.csv"
    .HorizontalAlignment = xlLeft
    .VerticalAlignment = xlTop
    .WrapText = True
  End With

  ws.Range("A12").value = "アクション"
  ws.Range("A12").Font.Bold = True
  ws.Range("A15").value = "ステータス"
  ws.Range("A15").Font.Bold = True
  ws.Range("B16:F16").Merge
  With ws.Range(CELL_STATUS)
    .value = "Ready"
    .HorizontalAlignment = xlLeft
    .VerticalAlignment = xlTop
    .WrapText = True
  End With

  ws.Range("A18").value = "Copilot診断レポート"
  ws.Range("A18").Font.Bold = True
  ClearCopilotDiagnosticsOutput ws

  DeleteButtons ws, "btnECM_*"
  AddButton ws, "btnECM_BrowseWb", LabelWithIcon("folder", "ターゲット選択"), ws.Range("B6"), 220, "ECM_BrowseWorkbook", True, "翻訳先となるExcelブックを選択します。"
  AddButton ws, "btnECM_BrowseCsv", LabelWithIcon("index", "辞書CSV選択"), ws.Range("B10"), 220, "ECM_BrowseCSV", True, "翻訳辞書となるCSVファイルを選択します。"
  AddButton ws, "btnECM_Apply", LabelWithIcon("check", "辞書翻訳"), ws.Range("B13"), 280, "ECM_ApplyTranslations", True, "辞書を使ってターゲットブックを翻訳します。"
  AddButton ws, "btnECM_Copilot", LabelWithIcon("robot", "copilot翻訳"), ws.Range("B14"), 280, "ECM_OpenCopilot", False, "Copilot for Microsoft 365 に接続し、ブラウザで翻訳を行います。"
  AddButton ws, "btnECM_DiagnoseCopilot", LabelWithIcon("info", "Copilot診断"), ws.Range("B17"), 260, "ECM_RunCopilotDiagnostics", False, "Copilot ブラウザ起動トラブルの診断を実行します。"

  With ws
    .Columns("A").ColumnWidth = 18
    .Columns("B").ColumnWidth = 54
    .Columns("C").ColumnWidth = 3
    .Columns("D").ColumnWidth = 3
    .Columns("E").ColumnWidth = 15
    .Columns("F").ColumnWidth = 8
    .Rows(1).RowHeight = 30
    .Rows(2).RowHeight = 24
    .Rows(4).RowHeight = 20
    .Rows(5).RowHeight = 44
    .Rows(6).RowHeight = 34
    .Rows(7).RowHeight = 12
    .Rows(8).RowHeight = 20
    .Rows(9).RowHeight = 44
    .Rows(10).RowHeight = 34
    .Rows(11).RowHeight = 12
    .Rows(12).RowHeight = 20
    .Rows(13).RowHeight = 38
    .Rows(14).RowHeight = 38
    .Rows(15).RowHeight = 20
    .Rows(16).RowHeight = 36
    .Rows(17).RowHeight = 32
    .Rows(18).RowHeight = 20
  End With

  Application.ScreenUpdating = True
  Application.DisplayAlerts = True

  MsgBox "翻訳パネルを準備しました。ターゲットブックと辞書CSVを確認してから「辞書翻訳」を実行するか、「copilot翻訳」でCopilotを開いてください。", vbInformation
End Sub

Private Function GetOrCreatePanel(Name As String) As Worksheet
  Dim ws As Worksheet
  On Error Resume Next
  Set ws = ThisWorkbook.Worksheets(Name)
  On Error GoTo 0
  If ws Is Nothing Then
    Set ws = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
    ws.Name = Name
  End If
  Set GetOrCreatePanel = ws
End Function

Private Sub DeleteButtons(ws As Worksheet, ByVal likeName As String)
  Dim shp As Shape
  On Error Resume Next
  For Each shp In ws.Shapes
    If shp.Name Like likeName Then shp.Delete
  Next
  On Error GoTo 0
End Sub

Private Sub AddButton(ws As Worksheet, _
                      ByVal btnName As String, ByVal caption As String, _
                      anchor As Range, ByVal w As Double, _
                      ByVal onAction As String, ByVal primary As Boolean, _
                      Optional ByVal tooltip As String = "")
  Dim shp As Shape
  On Error Resume Next
  ws.Shapes(btnName).Delete
  On Error GoTo 0
  Set shp = ws.Shapes.AddShape(msoShapeRoundedRectangle, anchor.Left, anchor.Top, w, anchor.RowHeight)
  With shp
    .Name = btnName
    .onAction = onAction
    .TextFrame2.TextRange.Characters.text = caption
    .TextFrame2.TextRange.ParagraphFormat.Alignment = msoAlignCenter
    .TextFrame2.VerticalAnchor = msoAnchorMiddle
    .TextFrame2.TextRange.Font.size = 10
    .TextFrame2.TextRange.Font.Bold = msoTrue
    On Error Resume Next
    If USE_EMOJI Then
      .TextFrame2.TextRange.Font.Name = "Segoe UI Emoji"
      If .TextFrame2.TextRange.Font.Name <> "Segoe UI Emoji" Then
        .TextFrame2.TextRange.Font.Name = "Segoe UI Symbol"
      End If
    Else
      .TextFrame2.TextRange.Font.Name = UI_FONT
    End If
    On Error GoTo 0
    If primary Then
      .Fill.ForeColor.RGB = COLOR_PRIMARY_LIGHT
      .line.ForeColor.RGB = COLOR_PRIMARY
      .TextFrame2.TextRange.Font.Fill.ForeColor.RGB = COLOR_PRIMARY
    Else
      .Fill.ForeColor.RGB = COLOR_BUTTON_BG
      .line.ForeColor.RGB = COLOR_BORDER
      .TextFrame2.TextRange.Font.Fill.ForeColor.RGB = RGB(60, 60, 60)
    End If
    If Len(tooltip) > 0 Then
      On Error Resume Next
      .AlternativeText = tooltip
      On Error GoTo 0
    End If
  End With
End Sub

'========================
'     ファイル選択/OPEN
'========================
Public Sub ECM_BrowseWorkbook()
  Dim ws As Worksheet: Set ws = ThisWorkbook.Worksheets(HELPER_SHEET)
  Dim fd As FileDialog: Set fd = Application.FileDialog(msoFileDialogFilePicker)
  With fd
    .Title = "Select Target Workbook"
    .AllowMultiSelect = False
    .Filters.Clear
    .Filters.Add "Excel Workbooks", "*.xlsx;*.xlsm;*.xls"
    If .Show = -1 Then ws.Range(COL_WB_PATH).value = .SelectedItems(1)
  End With
End Sub

Public Sub ECM_BrowseCSV()
  Dim ws As Worksheet: Set ws = ThisWorkbook.Worksheets(HELPER_SHEET)
  Dim fd As FileDialog: Set fd = Application.FileDialog(msoFileDialogFilePicker)
  With fd
    .Title = "Select Dictionary CSV"
    .AllowMultiSelect = False
    .Filters.Clear
    .Filters.Add "CSV", "*.csv"
    If .Show = -1 Then ws.Range(COL_CSV_PATH).value = .SelectedItems(1)
  End With
End Sub

Public Sub ECM_ApplyTranslations()
  Dim wsUI As Worksheet: Set wsUI = ThisWorkbook.Worksheets(HELPER_SHEET)
  Dim wb As Workbook: Set wb = GetTargetWorkbook(wsUI.Range(COL_WB_PATH).value & "")
  If wb Is Nothing Then
    MsgBox "Could not open target workbook.", vbExclamation
    Exit Sub
  End If

  Dim csvPath As String: csvPath = CleanPath(wsUI.Range(COL_CSV_PATH).value & "")
  If Len(csvPath) = 0 Then
    MsgBox "Please set Dictionary CSV path.", vbExclamation
    Exit Sub
  End If

  SetStatus "辞書を読み込み中..."
  Dim entries As Collection
  Set entries = EnsureDictionaryLoaded(csvPath)
  If (entries Is Nothing) Or (entries.Count = 0) Then
    Dim detailMsg As String
    detailMsg = LastCsvErrorDetail()
    If Len(detailMsg) > 0 Then detailMsg = " (" & detailMsg & ")"
    SetStatus "辞書の読み込みに失敗（空か形式不正）。" & detailMsg
    MsgBox "辞書が読み込めませんでした（空か、形式不正）。" & detailMsg, vbExclamation
    Exit Sub
  End If
  SetStatus "辞書読み込み完了: " & entries.Count & " 件"

  Dim targets As New Collection
  Dim ws As Worksheet
  For Each ws In wb.Worksheets
    If Not IsInternalSheet(ws) Then targets.Add ws
  Next ws

  If targets.Count = 0 Then
    SetStatus "翻訳対象のシートが見つかりません。"
    MsgBox "翻訳対象のシートが見つかりませんでした。", vbInformation
    Exit Sub
  End If

  If MsgBox("翻訳を実行します。" & vbCrLf & _
            "・対象ブック: " & wb.Name & vbCrLf & _
            "・対象シート数: " & targets.Count & vbCrLf & _
            "・辞書: " & csvPath & vbCrLf & _
            "よろしいですか？", vbQuestion + vbOKCancel) <> vbOK Then
    Exit Sub
  End If

  Dim oldCalc As XlCalculation: oldCalc = Application.Calculation
  On Error GoTo CleanFail
  Application.ScreenUpdating = False
  Application.Calculation = xlCalculationManual
  Application.EnableEvents = False

  Dim totalApplied As Long
  Dim processed As Long
  Dim targetSheet As Worksheet

  For Each targetSheet In targets
    processed = processed + 1
    If SheetProtected(targetSheet) Then
      SetStatus targetSheet.Name & ": 保護のためスキップ"
    Else
      SetStatus "翻訳中: " & targetSheet.Name & " (" & processed & "/" & targets.Count & ")"
      Application.StatusBar = "Applying translations to " & targetSheet.Name & "..."
      totalApplied = totalApplied + ApplyToSheet(targetSheet, entries)
    End If
    DoEvents
  Next targetSheet

  Application.StatusBar = False
  SetStatus "翻訳完了: " & totalApplied & " 件更新"
  MsgBox "翻訳が完了しました。変更セル/図形数: " & totalApplied & vbCrLf & "必要に応じて保存してください。", vbInformation
  GoTo CleanExit

CleanFail:
  Application.StatusBar = False
  Dim errMsg As String: errMsg = "翻訳中にエラーが発生しました: " & Err.description
  MsgBox errMsg, vbExclamation
  SetStatus errMsg

CleanExit:
  Application.EnableEvents = True
  Application.Calculation = oldCalc
  Application.ScreenUpdating = True
End Sub

'========================
'    Copilot 連携
'========================
Public Sub ECM_OpenCopilot()
  Const TARGET_URL As String = "https://m365.cloud.microsoft/chat/"
  On Error GoTo ErrH

  SetStatus "Copilotブラウザを初期化しています..."
  On Error GoTo 0
  If Not EnsureCopilotDriver() Then
    Err.Clear
    Exit Sub
  End If
  Err.Clear
  On Error GoTo ErrH

  SetStatus "Copilotへ接続中..."
  On Error Resume Next
  g_copilotDriver.Get TARGET_URL
  If Err.Number <> 0 Then
    Dim navErr As String
    navErr = "Copilotページへの接続に失敗しました: " & Err.description
    Err.Clear
    On Error GoTo ErrH
    SetStatus navErr
    MsgBox navErr, vbExclamation
    Exit Sub
  End If
  On Error GoTo ErrH

  SetStatus "Copilotの認証完了を待機しています..."
  Dim waitReason As String
  waitReason = ""
  If WaitForCopilotReady(g_copilotDriver, TARGET_URL, 300, waitReason) Then
    SetStatus "Copilot接続を確認しました。"
    MsgBox "Copilot for Microsoft 365 への接続を確認しました。ブラウザ上で翻訳を続けてください。", vbInformation
  Else
    Dim detail As String
    detail = "指定時間内にCopilotへの接続を確認できませんでした。"
    If Len(waitReason) > 0 Then
      detail = detail & vbCrLf & vbCrLf & "詳細: " & waitReason
    Else
      detail = detail & vbCrLf & vbCrLf & "ブラウザで認証やネットワーク状況を確認してください。"
    End If
    Dim statusDetail As String
    statusDetail = "Copilot接続の確認がタイムアウトしました。"
    If Len(waitReason) > 0 Then
      statusDetail = statusDetail & vbCrLf & "詳細: " & waitReason
    End If
    SetStatus statusDetail
    MsgBox detail, vbExclamation
  End If
  Exit Sub

ErrH:
  Dim errMsg As String
  errMsg = "Copilot翻訳の準備中にエラーが発生しました: " & Err.description
  SetStatus errMsg
  MsgBox errMsg, vbCritical
End Sub

Private Function EnsureCopilotDriver() As Boolean
  On Error Resume Next
  If Not g_copilotDriver Is Nothing Then
    Dim aliveTest As Variant
    aliveTest = g_copilotDriver.SessionId
    If Err.Number = 0 Then
      EnsureCopilotDriver = True
      On Error GoTo 0
      Exit Function
    End If
    Set g_copilotDriver = Nothing
    StopEdgeDriverService
    Err.Clear
  End If
  On Error GoTo 0

  RememberCopilotDiagPort 0

  Dim driverPath As String
  Dim haveDriver As Boolean
  haveDriver = False
  driverPath = ""
  ' Edge ドライバーを優先して準備
  Dim driverSetupError As String
  haveDriver = EnsureBrowserDriver("edge", driverPath, driverSetupError)
  If Not haveDriver Or Len(Trim$(driverPath)) = 0 Then
    Dim edgeSetupMsg As String
    edgeSetupMsg = "Copilotブラウザを起動できませんでした。Edgeドライバーの準備に失敗しました。"
    If Len(Trim$(driverSetupError)) > 0 Then
      edgeSetupMsg = edgeSetupMsg & vbCrLf & driverSetupError
    End If
    SetStatus edgeSetupMsg
    If Not IsSeleniumBasicInstalled() Then
      ShowSeleniumBasicInstallGuide
    Else
      MsgBox edgeSetupMsg & vbCrLf & vbCrLf & "Edge ドライバーの自動セットアップメッセージを確認し、手動で msedgedriver.exe を配置してください。", vbCritical
    End If
    StopEdgeDriverService
    EnsureCopilotDriver = False
    Exit Function
  End If

  Dim driver As Object
  Dim errorLog As String
  errorLog = ""

  Dim errDetail As String
  If Not TryStartDriver("Selenium.EdgeDriver", "edge", driver, driverPath, errDetail) Then
    If Len(errDetail) > 0 Then errorLog = errorLog & errDetail & vbCrLf

    Dim chromeDriver As Object
    Dim chromePath As String
    Dim chromeErr As String
    If EnsureBrowserDriver("chrome", chromePath, chromeErr) Then
      If TryStartDriver("Selenium.ChromeDriver", "chrome", chromeDriver, chromePath, chromeErr) Then
        Set g_copilotDriver = chromeDriver
        On Error Resume Next
        g_copilotDriver.Window.Maximize
        On Error GoTo 0
        SetStatus "Edge ドライバーの起動に失敗したため Chrome でフォールバックしました。"
        EnsureCopilotDriver = True
        Exit Function
      ElseIf Len(Trim$(chromeErr)) > 0 Then
        errorLog = AppendError(errorLog, chromeErr)
      End If
    ElseIf Len(Trim$(chromeErr)) > 0 Then
      errorLog = AppendError(errorLog, chromeErr)
    End If

    Dim finalMsg As String
    finalMsg = "Copilotブラウザを起動できませんでした。"
    Dim diagInfo As String
    If Len(Trim$(errorLog)) > 0 Then
      finalMsg = finalMsg & vbCrLf & Trim$(errorLog)
    End If
    Dim driverVersionInfo As String
    driverVersionInfo = GetExecutableVersion(driverPath)
    diagInfo = AppendError(diagInfo, "使用ドライバー: " & driverPath)
    If Len(driverVersionInfo) > 0 Then
      diagInfo = AppendError(diagInfo, "msedgedriver.exe バージョン: " & driverVersionInfo)
    End If
    Dim edgeVersionInfo As String
    edgeVersionInfo = GetInstalledEdgeVersion()
    If Len(edgeVersionInfo) > 0 Then
      diagInfo = AppendError(diagInfo, "Microsoft Edge バージョン: " & edgeVersionInfo)
    End If
    Dim driverHealth As String
    driverHealth = TestDriverExecutable(driverPath)
    If Len(driverHealth) > 0 Then
      diagInfo = AppendError(diagInfo, "msedgedriver.exe --version 実行結果: " & driverHealth)
    End If
    If InStr(1, errDetail, "listening port", vbTextCompare) > 0 Then
      diagInfo = AppendError(diagInfo, "推定原因: msedgedriver.exe がローカルループバック (127.0.0.1) のポートを開けません。エンドポイント保護ソフト、Windows Defender Application Control、あるいは企業プロキシでブロックされていないか確認してください。")
      diagInfo = AppendError(diagInfo, "対処案: セキュリティソフトの隔離ログで msedgedriver.exe の遮断有無を確認し、許可リストに追加してください。必要に応じてイントラネットの 127.0.0.1 通信を許可し、管理者権限で Excel/SeleniumBasic を再起動してから再試行してください。")
    End If
    If Len(diagInfo) > 0 Then
      finalMsg = finalMsg & vbCrLf & diagInfo
    End If
    SetStatus finalMsg
    If Not IsSeleniumBasicInstalled() Then
      ShowSeleniumBasicInstallGuide
    Else
      Dim detailMsg As String
      detailMsg = finalMsg & vbCrLf & vbCrLf & "SeleniumBasic とブラウザドライバーのインストール状況を確認してください。"
      MsgBox detailMsg, vbCritical
    End If
    StopEdgeDriverService
    EnsureCopilotDriver = False
    Exit Function
  End If

DriverReady:
  Set g_copilotDriver = driver
  On Error Resume Next
  g_copilotDriver.Window.Maximize
  On Error GoTo 0

  EnsureCopilotDriver = True
End Function

Public Sub ECM_RunCopilotDiagnostics()
  On Error GoTo EH
  SetStatus "Copilot診断を実行しています..."
  Dim report As String
  report = CollectCopilotDiagnostics()
  SetStatus "Copilot診断が完了しました。"
  CopyDiagnosticsToClipboard report
  WriteCopilotDiagnosticsReport report
  Dim ws As Worksheet
  On Error Resume Next
  Set ws = ThisWorkbook.Worksheets(HELPER_SHEET)
  If Not ws Is Nothing Then
    ws.Activate
    Application.Goto ws.Range("B" & COPILOT_DIAG_START_ROW), True
  End If
  On Error GoTo EH
  MsgBox "Copilot診断レポートをシートに出力し、クリップボードにもコピーしました。", vbInformation, "Copilot診断レポート"
  Exit Sub
EH:
  Dim errMsg As String
  errMsg = "Copilot診断中にエラーが発生しました: " & Err.Number & " " & Err.description
  SetStatus errMsg
  MsgBox errMsg, vbCritical, "Copilot診断エラー"
End Sub

Private Function LaunchEdgeDriverService(ByVal driverPath As String, _
                                         ByRef svcUrlOut As String, _
                                         ByRef pidOut As Long, _
                                         ByRef portOut As Long, _
                                         ByRef errOut As String) As Boolean
  On Error GoTo EH
  svcUrlOut = ""
  pidOut = 0
  portOut = 0
  errOut = ""
  LaunchEdgeDriverService = False

  StopEdgeDriverService
  KillProcessByImageName "msedgedriver.exe"
  g_edgeSvcPort = 0
  g_edgeSvcUrl = ""
  g_edgeSvcPid = 0
  Set g_edgeSvcExec = Nothing

  Dim baselinePids As Object
  Set baselinePids = CreateObject("Scripting.Dictionary")
  Dim existingPids As Collection
  Set existingPids = ListProcessIdsByImageName("msedgedriver.exe")
  If Not existingPids Is Nothing Then
    Dim bp As Variant
    For Each bp In existingPids
      baselinePids(Trim$(CStr(bp))) = True
    Next bp
  End If

  Dim sh As Object
  Set sh = CreateObject("WScript.Shell")
  If sh Is Nothing Then
    errOut = "WScript.Shell の初期化に失敗しました。"
    GoTo Fail
  End If

  Dim exec As Object
  Dim cmd As String
  cmd = """" & driverPath & """ --port=0 --allowed-origins=* --disable-build-check --verbose"
  Set exec = sh.exec(cmd)
  If exec Is Nothing Then
    errOut = "msedgedriver.exe の起動に失敗しました。"
    GoTo Fail
  End If
  Set g_edgeSvcExec = exec

  On Error Resume Next
  g_edgeSvcPid = exec.ProcessID
  On Error GoTo EH

  Dim stdoutBuf As String
  Dim stderrBuf As String
  Dim detectedPort As Long
  Dim startTick As Double
  stdoutBuf = ""
  stderrBuf = ""
  detectedPort = 0
  startTick = Timer

  Do
    DoEvents
    On Error Resume Next
    If Not exec.StdOut Is Nothing Then
      If Not exec.StdOut.AtEndOfStream Then
        stdoutBuf = stdoutBuf & exec.StdOut.Read(1024)
      End If
    End If
    If Not exec.StdErr Is Nothing Then
      If Not exec.StdErr.AtEndOfStream Then
        stderrBuf = stderrBuf & exec.StdErr.Read(1024)
      End If
    End If
    If g_edgeSvcPid = 0 Then
      Dim currentPids As Collection
      Set currentPids = ListProcessIdsByImageName("msedgedriver.exe")
      If Not currentPids Is Nothing Then
        Dim cp As Variant
        For Each cp In currentPids
          Dim pidKey As String
          pidKey = Trim$(CStr(cp))
          If Len(pidKey) > 0 Then
            If Not baselinePids.Exists(pidKey) Then
              g_edgeSvcPid = CLng(Val(pidKey))
              baselinePids(pidKey) = True
              Exit For
            End If
          End If
        Next cp
      End If
    End If
    On Error GoTo EH
    If Len(stdoutBuf) > 0 Then
      Dim parsedPort As Long
      parsedPort = DetectPortFromLogText(stdoutBuf)
      If parsedPort > 0 Then
        detectedPort = parsedPort
        Exit Do
      End If
    End If
    If exec.Status <> 0 Then Exit Do
    If SecondsElapsed(startTick) > 12# Then Exit Do
    PauseWithDoEvents 0.2
  Loop

  If detectedPort = 0 Then
    Dim portDescriptions As Collection
    Dim fallbackPort As Long
    fallbackPort = DetectEdgeDriverListeningPorts(portDescriptions)
    If fallbackPort > 0 Then
      If g_edgeSvcPid > 0 And Not portDescriptions Is Nothing Then
        Dim desc As Variant
        For Each desc In portDescriptions
          Dim descPid As String
          descPid = ExtractPidFromPortDescription(CStr(desc))
          If Len(descPid) > 0 Then
            If CLng(Val(descPid)) = g_edgeSvcPid Then
              Dim endpoint As String
              endpoint = ExtractEndpointFromPortDescription(CStr(desc))
              fallbackPort = ExtractPortFromEndpoint(endpoint)
              Exit For
            End If
          End If
        Next desc
      End If
      detectedPort = fallbackPort
    End If
  End If

  If g_edgeSvcPid = 0 Then
    Dim refreshedPids As Collection
    Set refreshedPids = ListProcessIdsByImageName("msedgedriver.exe")
    If Not refreshedPids Is Nothing Then
      Dim rp As Variant
      For Each rp In refreshedPids
        Dim pidCandidate As String
        pidCandidate = Trim$(CStr(rp))
        If Len(pidCandidate) > 0 Then
          If Not baselinePids.Exists(pidCandidate) Then
            g_edgeSvcPid = CLng(Val(pidCandidate))
            Exit For
          End If
        End If
      Next rp
    End If
  End If

  If detectedPort = 0 Then
    errOut = "EdgeDriver の待受ポートを検出できませんでした。"
    If Len(Trim$(stdoutBuf)) > 0 Then
      errOut = AppendError(errOut, Trim$(stdoutBuf))
    End If
    If Len(Trim$(stderrBuf)) > 0 Then
      errOut = AppendError(errOut, Trim$(stderrBuf))
    End If
    GoTo Fail
  End If

  Dim driverReady As Boolean
  Dim checkStart As Double
  driverReady = False
  checkStart = Timer
  Do
    Dim statusResult As String
    statusResult = TestDriverEndpoint(detectedPort)
    If statusResult Like "HTTP 200 *" Then
      driverReady = True
      Exit Do
    End If
    If SecondsElapsed(checkStart) > 15# Then Exit Do
    PauseWithDoEvents 0.4
  Loop
  If Not driverReady Then
    errOut = "EdgeDriver の /status が所定時間内に 200 を返しませんでした。"
    GoTo Fail
  End If

  g_edgeSvcPort = detectedPort
  g_edgeSvcUrl = "http://127.0.0.1:" & CStr(detectedPort) & "/"

  svcUrlOut = g_edgeSvcUrl
  pidOut = g_edgeSvcPid
  portOut = g_edgeSvcPort
  LaunchEdgeDriverService = True
  Exit Function

Fail:
  StopEdgeDriverService
  If Len(errOut) = 0 Then
    errOut = "EdgeDriver の起動に失敗しました。"
  End If
  Exit Function

EH:
  errOut = "LaunchEdgeDriverService: " & Err.Number & " " & Err.description
  Resume Fail
End Function

Private Sub StopEdgeDriverService()
  On Error Resume Next
  If Not g_edgeSvcExec Is Nothing Then
    g_edgeSvcExec.Terminate
  End If
  Set g_edgeSvcExec = Nothing
  If g_edgeSvcPid > 0 Then
    Dim sh As Object
    Set sh = CreateObject("WScript.Shell")
    If Not sh Is Nothing Then
      sh.Run "cmd /c taskkill /F /PID " & CStr(g_edgeSvcPid) & " >NUL 2>&1", 0, True
    End If
  End If
  g_edgeSvcPid = 0
  g_edgeSvcPort = 0
  g_edgeSvcUrl = ""
  On Error GoTo 0
End Sub

Private Function TryStartDriver(ByVal progId As String, ByVal browserName As String, ByRef driverOut As Object, Optional ByVal driverPath As String = "", Optional ByRef errOut As String = "", Optional ByVal skipProcessCleanup As Boolean = False) As Boolean
  errOut = ""
  Dim lastError As String
  Dim lowerBrowser As String
  lowerBrowser = LCase$(Trim$(browserName))
  Dim remoteDriver As Object

  If lowerBrowser = "edge" And Len(Trim$(driverPath)) > 0 Then
    Dim svcUrl As String
    Dim svcPid As Long
    Dim svcPort As Long
    Dim svcErr As String
    If LaunchEdgeDriverService(driverPath, svcUrl, svcPid, svcPort, svcErr) Then
      On Error Resume Next
      Set remoteDriver = CreateObject("Selenium.WebDriver")
      If Err.Number <> 0 Or remoteDriver Is Nothing Then
        lastError = AppendError(lastError, "Selenium.WebDriver の生成に失敗しました: " & Err.description)
        Err.Clear
      Else
        remoteDriver.AddDriver "MicrosoftEdge", driverPath
        remoteDriver.Start "edge", svcUrl
        If Err.Number <> 0 Then
          lastError = AppendError(lastError, "EdgeDriver サービスへの接続に失敗しました: " & Err.description)
          Err.Clear
        Else
          On Error GoTo 0
          Set driverOut = remoteDriver
          RememberCopilotDiagPort svcPort
          TryStartDriver = True
          Exit Function
        End If
      End If
      On Error GoTo 0
      On Error Resume Next
      If Not remoteDriver Is Nothing Then
        remoteDriver.Quit
      End If
      On Error GoTo 0
      Set remoteDriver = Nothing
      StopEdgeDriverService
    Else
      lastError = AppendError(lastError, svcErr)
    End If
  End If

  If Not skipProcessCleanup Then
    KillProcessByImageName "msedgedriver.exe"
    KillProcessByImageName "chromedriver.exe"
  End If

  On Error Resume Next
  Set driverOut = CreateObject(progId)
  If driverOut Is Nothing Then
    lastError = AppendError(lastError, "ドライバー生成に失敗しました (" & progId & ").")
    Err.Clear
    GoTo Fail
  End If

  If Len(Trim$(driverPath)) > 0 Then
    CallByName driverOut, "AddDriver", VbMethod, "msedgedriver.exe", driverPath
    CallByName driverOut, "AddDriver", VbMethod, "MicrosoftEdge", driverPath
  End If
  CallByName driverOut, "AddArgument", VbMethod, "--allowed-origins=*"
  CallByName driverOut, "AddArgument", VbMethod, "--disable-build-check"
  CallByName driverOut, "AddArgument", VbMethod, "--verbose"
  On Error GoTo 0
  Err.Clear

  On Error Resume Next
  If lowerBrowser = "edge" Then
    driverOut.browser = "edge"
  End If
  driverOut.Start IIf(lowerBrowser = "edge", "edge", browserName)
  If Err.Number <> 0 Then
    lastError = AppendError(lastError, "Selenium起動エラー(" & browserName & "): " & Err.Number & " " & Err.description)
    Err.Clear
    If lowerBrowser = "edge" Then
      driverOut.Start "MicrosoftEdge"
      If Err.Number <> 0 Then
        lastError = AppendError(lastError, "Selenium起動エラー(" & browserName & "): " & Err.Number & " " & Err.description)
        Err.Clear
        GoTo Fail
      End If
    Else
      GoTo Fail
    End If
  End If
  On Error GoTo Fail

  PauseWithDoEvents 0.6

  Dim startTickWait As Double
  Dim okSession As Boolean
  startTickWait = Timer
  Do
    On Error Resume Next
    okSession = (Len(Trim$(CStr(driverOut.SessionId))) > 0)
    Err.Clear
    On Error GoTo Fail
    If okSession Then Exit Do
    If SecondsElapsed(startTickWait) > 3 Then Exit Do
    PauseWithDoEvents 0.2
  Loop
  If Not okSession Then
    lastError = AppendError(lastError, "ブラウザセッションの初期化に失敗しました(" & browserName & ").")
    GoTo Fail
  End If

  On Error Resume Next
  driverOut.Get "about:blank"
  If Err.Number <> 0 Then
    lastError = AppendError(lastError, "ブラウザ起動直後に失敗しました(" & browserName & "): " & Err.Number & " " & Err.description)
    Err.Clear
    GoTo Fail
  End If

  Err.Clear
  On Error GoTo 0
  If lowerBrowser <> "edge" Or g_edgeSvcPort = 0 Then
    RememberCopilotDiagPort 0
  End If
  TryStartDriver = True
  Exit Function

Fail:
  On Error Resume Next
  If Not driverOut Is Nothing Then
    driverOut.Quit
  End If
  Set driverOut = Nothing
  Err.Clear
  On Error GoTo 0
  StopEdgeDriverService

  errOut = Trim$(lastError)
  Dim diagPort As Long
  diagPort = ExtractPortFromError(errOut)
  If diagPort > 0 Then
    RememberCopilotDiagPort diagPort
    Dim portDiagInfo As String
    On Error GoTo PortDiagFail
    portDiagInfo = CollectPortDiagnostics(diagPort)
    On Error GoTo 0
    If Len(portDiagInfo) > 0 Then
      errOut = AppendError(errOut, portDiagInfo)
    End If
  End If
  If InStr(1, errOut, "listening port", vbTextCompare) > 0 Then
    errOut = errOut & vbCrLf & "Edgeドライバーがローカルポートを開くことに失敗しました。ウイルス対策ソフトやファイアウォール、アプリケーション制御で msedgedriver.exe の実行が阻害されていないか確認してください。"
  End If
  TryStartDriver = False
  Exit Function

PortDiagFail:
  Dim diagErrMsg As String
  diagErrMsg = "ポート診断の実行に失敗しました: " & Err.description
  errOut = AppendError(errOut, diagErrMsg)
  SetStatus diagErrMsg
  Err.Clear
  TryStartDriver = False
  Exit Function
End Function

Private Function ExtractPortFromError(ByVal message As String) As Long
  On Error GoTo EH
  Dim re As Object
  Set re = CreateObject("VBScript.RegExp")
  If re Is Nothing Then Exit Function
  re.Pattern = "127\.0\.0\.1:(\d+)"
  re.IgnoreCase = True
  re.Global = False
  If re.Test(message) Then
    ExtractPortFromError = CLng(re.Execute(message)(0).SubMatches(0))
  End If
  Exit Function
EH:
  ExtractPortFromError = 0
End Function

Private Function SuggestEdgeDriverPort() As Long
  On Error GoTo EH
  If g_lastCopilotDiagPort > 0 Then
    RememberCopilotDiagPort g_lastCopilotDiagPort
    SuggestEdgeDriverPort = g_lastCopilotDiagPort
    Exit Function
  End If
  Dim ws As Worksheet
  Set ws = ThisWorkbook.Worksheets(HELPER_SHEET)
  Dim recentStatus As String
  recentStatus = CStr(ws.Range(CELL_STATUS).value)
  Dim portValue As Long
  portValue = ExtractPortFromError(recentStatus)
  If portValue > 0 Then
    RememberCopilotDiagPort portValue
    SuggestEdgeDriverPort = portValue
    Exit Function
  End If
  Dim diagRange As Range
  On Error Resume Next
  Set diagRange = ws.Range("Diag_PortValue")
  On Error GoTo EH
  If Not diagRange Is Nothing Then
    Dim cellText As String
    cellText = CStr(diagRange.value)
    portValue = ExtractPortFromError(cellText)
    If portValue > 0 Then
      RememberCopilotDiagPort portValue
      SuggestEdgeDriverPort = portValue
      Exit Function
    End If
  End If
  SuggestEdgeDriverPort = 0
  Exit Function
EH:
  SuggestEdgeDriverPort = 0
End Function

Private Sub RememberCopilotDiagPort(ByVal portNumber As Long)
  On Error GoTo EH
  g_lastCopilotDiagPort = portNumber

  Dim ws As Worksheet
  On Error Resume Next
  Set ws = ThisWorkbook.Worksheets(HELPER_SHEET)
  On Error GoTo EH
  If ws Is Nothing Then Exit Sub

  Dim diagRange As Range
  On Error Resume Next
  Set diagRange = ws.Range("Diag_PortValue")
  On Error GoTo EH
  If diagRange Is Nothing Then Exit Sub

  If portNumber > 0 Then
    diagRange.value = "127.0.0.1:" & portNumber
  Else
    diagRange.value = ""
  End If
  Exit Sub
EH:
  ' 診断ポートの保存に失敗しても処理は継続
End Sub

Private Sub ClearCopilotDiagnosticsOutput(ByVal ws As Worksheet)
  On Error GoTo EH
  Dim startRow As Long
  startRow = COPILOT_DIAG_START_ROW
  Dim maxRows As Long
  maxRows = COPILOT_DIAG_MAX_LINES
  ws.Range("B" & startRow & ":B" & (startRow + maxRows)).ClearContents
  Exit Sub
EH:
  ' クリア失敗時も無視
End Sub

Private Sub WriteCopilotDiagnosticsReport(ByVal report As String)
  On Error GoTo EH
  Dim ws As Worksheet
  Set ws = ThisWorkbook.Worksheets(HELPER_SHEET)
  ClearCopilotDiagnosticsOutput ws

  Dim lines As Variant
  lines = Split(CStr(report), vbCrLf)
  Dim limit As Long
  limit = UBound(lines)
  If limit > COPILOT_DIAG_MAX_LINES Then
    limit = COPILOT_DIAG_MAX_LINES
  End If

  Dim i As Long
  Dim baseRow As Long
  baseRow = COPILOT_DIAG_START_ROW
  For i = 0 To limit
    ws.Range("B" & (baseRow + i)).value = lines(i)
    ws.Range("B" & (baseRow + i)).WrapText = False
  Next i

  Dim lastRow As Long
  lastRow = baseRow + limit
  ws.Range("B" & baseRow & ":B" & lastRow).EntireRow.AutoFit
  Exit Sub
EH:
  ' 表示に失敗しても処理は継続
End Sub

Private Function CollectPortDiagnostics(ByVal portNumber As Long) As String
  Dim report As String
  report = AppendLine(report, "ポート診断:")
  report = AppendLine(report, "  対象ポート: " & portNumber)

  Dim iphlpPath As String
  Dim iphlpVersion As String
  iphlpPath = CombinePath(Environ$("SystemRoot"), "System32\iphlpapi.dll")
  If Len(Trim$(iphlpPath)) = 0 Then iphlpPath = "C:\Windows\System32\iphlpapi.dll"
  iphlpVersion = GetExecutableVersion(iphlpPath)
  If Len(iphlpVersion) = 0 Then
    Err.Raise vbObjectError + 2102, "CollectPortDiagnostics", _
      "netsh診断を中止しました: iphlpapi.dll のバージョンを取得できませんでした。システムファイルを検証してから再試行してください。"
  ElseIf VersionCompare(iphlpVersion, MIN_IPHLPAPI_VERSION_FOR_NETSH) < 0 Then
    Err.Raise vbObjectError + 2103, "CollectPortDiagnostics", _
      "netsh診断を中止しました: iphlpapi.dll バージョン (" & iphlpVersion & ") が古いため序数538が存在しません。Windows Update を適用してから再試行してください。"
  End If

  Dim netstatOut As String, netstatErr As String, netstatExit As Long
  If ExecuteCommand("netstat -ano -p tcp", netstatOut, netstatErr, 10, netstatExit) Then
    Dim listenerLine As String
    listenerLine = FindNetstatLine(netstatOut, portNumber)
    If Len(listenerLine) > 0 Then
      report = AppendLine(report, "  netstat: LISTEN 状態のエントリを検出しました。")
      report = AppendLine(report, "    " & listenerLine)
      Dim pid As String
      pid = ExtractPidFromNetstatLine(listenerLine)
      If Len(pid) > 0 Then
        Dim taskOut As String, taskErr As String, taskExit As Long
        If ExecuteCommand("tasklist /FI ""PID eq " & pid & """", taskOut, taskErr, 10, taskExit) Then
          Dim taskInfo As String
          taskInfo = ExtractFirstNonHeaderLine(taskOut)
          If Len(taskInfo) > 0 Then
            report = AppendLine(report, "  tasklist: PID " & pid & " -> " & taskInfo)
          End If
        ElseIf Len(Trim$(taskErr)) > 0 Then
          report = AppendLine(report, "  tasklist: 取得失敗 (" & taskErr & ")")
        End If
      End If
    Else
      report = AppendLine(report, "  netstat: 対象ポートを使用中のエントリは検出されませんでした。")
    End If
  Else
    report = AppendLine(report, "  netstat: 実行に失敗 (" & netstatErr & ")")
  End If

  Dim excludedOut As String, excludedErr As String, excludedExit As Long
  If ExecuteCommand("netsh int ipv4 show excludedportrange protocol=tcp", excludedOut, excludedErr, 10, excludedExit) Then
    Dim excludedInfo As String
    excludedInfo = DetectExcludedRange(excludedOut, portNumber)
    If Len(excludedInfo) > 0 Then
      report = AppendLine(report, "  netsh: 対象ポートは予約済みポート範囲に含まれます。")
      report = AppendLine(report, "    " & excludedInfo)
    Else
      report = AppendLine(report, "  netsh: 対象ポートは予約済みポート範囲に含まれていません。")
    End If
  Else
    report = AppendLine(report, "  netsh: 予約ポート情報を取得できませんでした (" & excludedErr & ")")
  End If

  Dim dynOut As String, dynErr As String, dynExit As Long
  If ExecuteCommand("netsh int ipv4 show dynamicport tcp", dynOut, dynErr, 10, dynExit) Then
    Dim dynLine As Variant
    report = AppendLine(report, "  netsh: DynamicPort (TCP)")
    For Each dynLine In Split(dynOut, vbCrLf)
      If Len(Trim$(CStr(dynLine))) > 0 Then
        report = AppendLine(report, "    " & CStr(dynLine))
      End If
    Next dynLine
  ElseIf Len(Trim$(dynErr)) > 0 Then
    report = AppendLine(report, "  netsh: DynamicPort (TCP) 取得失敗 (" & dynErr & ")")
  End If

  report = AppendLine(report, "  PowerShell: スキップ（コマンドライン診断のみ実施）")

  CollectPortDiagnostics = Trim$(report)
End Function

Private Function ExecuteCommand(ByVal command As String, ByRef stdoutOut As String, ByRef stderrOut As String, Optional ByVal timeoutSeconds As Long = 10, Optional ByRef exitCodeOut As Long) As Boolean
  On Error GoTo EH
  Dim shell As Object
  Set shell = CreateObject("WScript.Shell")
  If shell Is Nothing Then GoTo EH

  Dim stdoutPath As String
  Dim stderrPath As String
  stdoutPath = CreateTempFile("ecm_cmd_", ".out")
  stderrPath = CreateTempFile("ecm_cmd_", ".err")
  If Len(stdoutPath) = 0 Or Len(stderrPath) = 0 Then GoTo EH

  Dim cmdLine As String
  Dim comspec As String
  comspec = Environ$("ComSpec")
  If Len(comspec) = 0 Then comspec = "cmd.exe"
  cmdLine = """" & comspec & """ /C " & command & " 1>""" & stdoutPath & """ 2>""" & stderrPath & """"

  exitCodeOut = shell.Run(cmdLine, 0, True)
  stdoutOut = ReadAllTextUTF8(stdoutPath)
  stderrOut = ReadAllTextUTF8(stderrPath)
  ExecuteCommand = (exitCodeOut = 0)
  If Not ExecuteCommand Then
    Err.Raise vbObjectError + 2101, "ExecuteCommand", "コマンド実行に失敗しました: " & command & " (ExitCode=" & exitCodeOut & ")"
  End If

Cleanup:
  DeleteFileSafe stdoutPath
  DeleteFileSafe stderrPath
  Exit Function

EH:
  stdoutOut = ""
  stderrOut = Err.description
  exitCodeOut = -1
  ExecuteCommand = False
  Resume Cleanup
End Function

Private Sub KillProcessByImageName(ByVal imageName As String)
  On Error Resume Next
  Dim sh As Object
  Set sh = CreateObject("WScript.Shell")
  If sh Is Nothing Then Exit Sub
  sh.Run "cmd /c taskkill /F /IM " & imageName & " >NUL 2>&1", 0, True
  On Error GoTo 0
End Sub

Private Function FindNetstatLine(ByVal netstatOutput As String, ByVal portNumber As Long) As String
  Dim lines() As String
  lines = Split(netstatOutput, vbCrLf)
  Dim line As Variant
  For Each line In lines
    Dim normalized As String
    normalized = NormalizeWhitespace(Trim$(CStr(line)))
    If Len(normalized) = 0 Then GoTo NextLine
    Dim parts() As String
    parts = Split(normalized, " ")
    If UBound(parts) >= 1 Then
      Dim proto As String
      proto = UCase$(parts(0))
      If proto = "TCP" Or proto = "UDP" Then
        Dim localEndpoint As String
        localEndpoint = parts(1)
        If ExtractPortFromEndpoint(localEndpoint) = portNumber Then
          FindNetstatLine = normalized
          Exit Function
        End If
      End If
    End If
NextLine:
  Next line
End Function

Private Function ExtractPidFromNetstatLine(ByVal netstatLine As String) As String
  Dim normalized As String
  normalized = NormalizeWhitespace(netstatLine)
  Dim parts() As String
  parts = Split(normalized, " ")
  If UBound(parts) >= 4 Then
    ExtractPidFromNetstatLine = parts(UBound(parts))
  End If
End Function

Private Function ExtractFirstNonHeaderLine(ByVal textBlock As String) As String
  Dim lines() As String
  lines = Split(textBlock, vbCrLf)
  Dim line As Variant
  For Each line In lines
    Dim trimmed As String
    trimmed = Trim$(CStr(line))
    If Len(trimmed) = 0 Then GoTo NextLine
    If InStr(1, trimmed, "==", vbTextCompare) > 0 Then GoTo NextLine
    If LCase$(trimmed) Like "*no tasks are running*" Then GoTo NextLine
    ExtractFirstNonHeaderLine = trimmed
    Exit Function
NextLine:
  Next line
End Function

Private Function ListProcessIdsByImageName(ByVal imageName As String) As Collection
  On Error GoTo EH
  Dim results As Collection
  Set results = New Collection

  Dim stdout As String
  Dim stderr As String
  Dim exitCode As Long
  Dim command As String
  command = "tasklist /FI ""IMAGENAME eq " & imageName & """"
  If Not ExecuteCommand(command, stdout, stderr, 10, exitCode) Then
    GoTo Done
  End If

  Dim lines() As String
  lines = Split(stdout, vbCrLf)
  Dim line As Variant
  For Each line In lines
    Dim trimmed As String
    trimmed = Trim$(CStr(line))
    If Len(trimmed) = 0 Then GoTo NextLine
    Dim normalized As String
    normalized = NormalizeWhitespace(trimmed)
    If Len(normalized) = 0 Then GoTo NextLine
    If StrComp(Left$(normalized, Len(imageName)), imageName, vbTextCompare) = 0 Then
      Dim parts() As String
      parts = Split(normalized, " ")
      If UBound(parts) >= 1 Then
        Dim pidValue As String
        pidValue = parts(1)
        If Len(pidValue) > 0 Then
          On Error Resume Next
          results.Add pidValue
          On Error GoTo EH
        End If
      End If
    End If
NextLine:
  Next line

Done:
  Set ListProcessIdsByImageName = results
  Exit Function
EH:
  Set results = New Collection
  Set ListProcessIdsByImageName = results
End Function

Private Function ExtractPortFromEndpoint(ByVal endpoint As String) As Long
  On Error GoTo EH
  Dim cleaned As String
  cleaned = Trim$(endpoint)
  If Len(cleaned) = 0 Then Exit Function
  If Left$(cleaned, 1) = "[" Then
    Dim closing As Long
    closing = InStr(cleaned, "]")
    If closing > 0 Then
      cleaned = Mid$(cleaned, closing + 1)
    End If
  End If
  Dim colonPos As Long
  colonPos = InStrRev(cleaned, ":")
  If colonPos = 0 Then Exit Function
  ExtractPortFromEndpoint = CLng(Val(Mid$(cleaned, colonPos + 1)))
  Exit Function
EH:
  ExtractPortFromEndpoint = 0
End Function

Private Function DetectEdgeDriverListeningPorts(ByRef portDescriptions As Collection) As Long
  On Error GoTo EH
  Dim imageName As String
  imageName = "msedgedriver.exe"
  Dim pids As Collection
  Set pids = ListProcessIdsByImageName(imageName)
  If pids Is Nothing Then Exit Function
  If pids.Count = 0 Then Exit Function

  Dim pidSet As Object
  Set pidSet = CreateObject("Scripting.Dictionary")
  Dim pid As Variant
  For Each pid In pids
    pidSet(Trim$(CStr(pid))) = True
  Next pid

  Dim netstatOut As String
  Dim netstatErr As String
  Dim netstatExit As Long
  If Not ExecuteCommand("netstat -ano -p tcp", netstatOut, netstatErr, 10, netstatExit) Then Exit Function

  Dim firstPort As Long
  firstPort = 0
  Dim lines() As String
  lines = Split(netstatOut, vbCrLf)
  Dim line As Variant
  For Each line In lines
    Dim trimmed As String
    trimmed = Trim$(CStr(line))
    If Len(trimmed) = 0 Then GoTo NextLine
    Dim normalized As String
    normalized = NormalizeWhitespace(trimmed)
    If Len(normalized) = 0 Then GoTo NextLine
    Dim parts() As String
    parts = Split(normalized, " ")
    If UBound(parts) < 4 Then GoTo NextLine
    Dim proto As String
    proto = parts(0)
    If StrComp(proto, "TCP", vbTextCompare) <> 0 Then GoTo NextLine
    Dim state As String
    state = parts(3)
    If InStr(1, state, "LISTEN", vbTextCompare) = 0 Then GoTo NextLine
    Dim pidValue As String
    pidValue = parts(UBound(parts))
    If Not pidSet.Exists(pidValue) Then GoTo NextLine
    Dim localEndpoint As String
    localEndpoint = parts(1)
    Dim portNumber As Long
    portNumber = ExtractPortFromEndpoint(localEndpoint)
    If portNumber = 0 Then GoTo NextLine
    If firstPort = 0 Then firstPort = portNumber
    If portDescriptions Is Nothing Then
      Set portDescriptions = New Collection
    End If
    On Error Resume Next
    portDescriptions.Add "PID " & pidValue & " -> " & localEndpoint
    On Error GoTo EH
NextLine:
  Next line

  DetectEdgeDriverListeningPorts = firstPort
  Exit Function
EH:
  DetectEdgeDriverListeningPorts = 0
End Function

Private Function ProbeEdgeDriverListeningPort(ByVal driverPath As String, ByRef logLinesOut As Collection, ByRef errOut As String) As Long
  On Error GoTo EH
  errOut = ""

  Dim baselinePids As Object
  Set baselinePids = CreateObject("Scripting.Dictionary")
  Dim existingPids As Collection
  Set existingPids = ListProcessIdsByImageName("msedgedriver.exe")
  If Not existingPids Is Nothing Then
    Dim bp As Variant
    For Each bp In existingPids
      baselinePids(Trim$(CStr(bp))) = True
    Next bp
  End If

  Dim shell As Object
  Set shell = CreateObject("WScript.Shell")
  If shell Is Nothing Then
    errOut = "WScript.Shell を初期化できません。"
    Exit Function
  End If

  Dim cmd As String
  cmd = """" & driverPath & """ --port=0 --allowed-origins=* --disable-build-check --verbose"
  Dim exec As Object
  Set exec = shell.exec(cmd)
  Dim startTick As Double
  startTick = Timer
  Dim portNumber As Long
  portNumber = 0

  Dim probeDescriptions As Collection
  Set probeDescriptions = New Collection
  Dim loggedDescriptors As Object
  Set loggedDescriptors = CreateObject("Scripting.Dictionary")

  Do
    Dim currentDescriptions As Collection
    Call DetectEdgeDriverListeningPorts(currentDescriptions)
    If Not currentDescriptions Is Nothing Then
      Dim desc As Variant
      For Each desc In currentDescriptions
        Dim descriptor As String
        descriptor = CStr(desc)
        Dim descPid As String
        Dim descPort As Long
        descPid = ExtractPidFromPortDescription(descriptor)
        descPort = ExtractPortFromEndpoint(ExtractEndpointFromPortDescription(descriptor))
        If Len(descPid) > 0 Then
          If Not baselinePids.Exists(descPid) And descPort > 0 Then
            portNumber = descPort
            baselinePids(descPid) = True
          End If
        End If
        If Not loggedDescriptors.Exists(descriptor) Then
          probeDescriptions.Add descriptor
          loggedDescriptors(descriptor) = True
        End If
      Next desc
    End If
    If portNumber > 0 Then Exit Do
    If exec.status <> 0 Then Exit Do
    If SecondsElapsed(startTick) > 12 Then Exit Do
    PauseWithDoEvents 0.3
  Loop

  If portNumber > 0 Then
    PauseWithDoEvents 0.5
    If logLinesOut Is Nothing Then Set logLinesOut = New Collection
    AppendTextBlockToCollection logLinesOut, "probe_http: " & TestDriverEndpoint(portNumber)
  End If

  If exec.status = 0 Then
    On Error Resume Next
    exec.Terminate
    On Error GoTo EH
  End If

  Dim stdoutText As String
  Dim stderrText As String
  stdoutText = ""
  stderrText = ""
  On Error Resume Next
  If Not exec Is Nothing Then
    stdoutText = Trim$(stdoutText & IIf(Len(stdoutText) > 0, vbCrLf, "") & exec.stdout.ReadAll)
    stderrText = Trim$(stderrText & IIf(Len(stderrText) > 0, vbCrLf, "") & exec.stderr.ReadAll)
  End If
  On Error GoTo EH

  If logLinesOut Is Nothing Then Set logLinesOut = New Collection
  Dim pd As Variant
  For Each pd In probeDescriptions
    AppendTextBlockToCollection logLinesOut, "probe: " & CStr(pd)
  Next pd
  If Len(stdoutText) > 0 Then
    AppendTextBlockToCollection logLinesOut, "stdout: " & Replace(stdoutText, vbCrLf, " / ")
  End If
  If Len(stderrText) > 0 Then
    AppendTextBlockToCollection logLinesOut, "stderr: " & Replace(stderrText, vbCrLf, " / ")
  End If

  If portNumber = 0 Then
    If exec.status <> 0 Then
      errOut = "ExitCode=" & exec.exitCode
    ElseIf Len(errOut) = 0 Then
      errOut = "ポート情報を取得できませんでした。"
    End If
  End If

  ProbeEdgeDriverListeningPort = portNumber
  Exit Function
EH:
  errOut = Err.Number & " " & Err.description
  On Error Resume Next
  If Not exec Is Nothing Then exec.Terminate
  On Error GoTo 0
End Function

Private Function TestDriverEndpoint(ByVal port As Long) As String
  On Error GoTo EH
  Dim req As Object
  Set req = CreateHttpRequest()
  If req Is Nothing Then
    TestDriverEndpoint = "HTTP init failed"
    Exit Function
  End If
  On Error Resume Next
  req.setTimeouts 5000, 5000, 5000, 5000
  On Error GoTo EH
  Dim url As String
  url = "http://127.0.0.1:" & port & "/status"
  req.Open "GET", url, False
  req.setRequestHeader "Accept", "application/json"
  req.Send
  TestDriverEndpoint = "HTTP " & req.status & " " & req.statusText
  Exit Function
EH:
  TestDriverEndpoint = "Error " & Err.Number & " " & Err.description
End Function

Private Function RunSeleniumBasicDriverProbe(ByVal driverPath As String, ByRef linesOut As Collection, ByRef errOut As String) As Boolean
  Dim driver As Object
  Dim errDetail As String
  errOut = ""

  If TryStartDriver("Selenium.EdgeDriver", "edge", driver, driverPath, errDetail, True) Then
    RunSeleniumBasicDriverProbe = True
    If linesOut Is Nothing Then Set linesOut = New Collection
    On Error Resume Next
    AppendTextBlockToCollection linesOut, "SeleniumBasic: SessionId=" & CStr(driver.SessionId)
    On Error GoTo 0
  Else
    errOut = errDetail
    If linesOut Is Nothing Then Set linesOut = New Collection
    If Len(Trim$(errDetail)) > 0 Then
      Dim extraLine As Variant
      For Each extraLine In Split(errDetail, vbCrLf)
        If Len(Trim$(CStr(extraLine))) > 0 Then
          AppendTextBlockToCollection linesOut, "detail: " & CStr(extraLine)
        End If
      Next extraLine
    End If
  End If

  On Error Resume Next
  If Not driver Is Nothing Then driver.Quit
  Set driver = Nothing
  On Error GoTo 0
End Function

Private Function LogTailLines(ByVal textValue As String, ByVal maxLines As Long) As Collection
  Dim result As Collection
  Set result = New Collection
  If maxLines <= 0 Then
    Set LogTailLines = result
    Exit Function
  End If
  Dim lines() As String
  lines = Split(CStr(textValue), vbCrLf)
  Dim ub As Long
  ub = UBound(lines)
  If ub < 0 Then
    Set LogTailLines = result
    Exit Function
  End If
  Dim startIndex As Long
  startIndex = ub - maxLines + 1
  If startIndex < 0 Then startIndex = 0
  Dim i As Long
  For i = startIndex To ub
    Dim trimmed As String
    trimmed = Trim$(lines(i))
    If Len(trimmed) > 0 Then
      result.Add trimmed
    End If
  Next i
  Set LogTailLines = result
End Function

Private Sub AppendTextBlockToCollection(ByVal target As Collection, ByVal textValue As String)
  Dim cleaned As String
  cleaned = Trim$(CStr(textValue))
  If Len(cleaned) = 0 Then Exit Sub
  target.Add cleaned
End Sub

Private Function DetectPortFromLogText(ByVal textValue As String) As Long
  Dim port As Long
  port = ExtractPortFromError(textValue)
  If port > 0 Then
    DetectPortFromLogText = port
    Exit Function
  End If
  On Error GoTo EH
  Dim re As Object
  Set re = CreateObject("VBScript.RegExp")
  If re Is Nothing Then Exit Function
  re.Global = False
  re.IgnoreCase = True

  re.Pattern = "port\s*[:=]\s*(\d+)"
  If re.Test(textValue) Then
    DetectPortFromLogText = CLng(re.Execute(textValue)(0).SubMatches(0))
    Exit Function
  End If

  re.Pattern = "listening\s+on[^0-9]*(\d+)"
  If re.Test(textValue) Then
    DetectPortFromLogText = CLng(re.Execute(textValue)(0).SubMatches(0))
    Exit Function
  End If

  re.Pattern = "ws://[0-9.:]*:(\d+)"
  If re.Test(textValue) Then
    DetectPortFromLogText = CLng(re.Execute(textValue)(0).SubMatches(0))
    Exit Function
  End If
  Exit Function
EH:
  DetectPortFromLogText = 0
End Function

Private Function DetectOSArchitecture() As String
  Dim arch As String
  arch = LCase$(Trim$(Environ$("PROCESSOR_ARCHITECTURE")))
  Dim wow64 As String
  wow64 = LCase$(Trim$(Environ$("PROCESSOR_ARCHITEW6432")))

  If InStr(arch, "64") > 0 Then
    DetectOSArchitecture = "64-bit"
  ElseIf arch = "x86" Then
    If Len(wow64) > 0 Then
      DetectOSArchitecture = "64-bit (WoW64)"
    Else
      DetectOSArchitecture = "32-bit"
    End If
  ElseIf Len(arch) > 0 Then
    DetectOSArchitecture = arch
  Else
    DetectOSArchitecture = "不明"
  End If
End Function

Private Function DetectOfficeArchitecture() As String
#If Win64 Then
  DetectOfficeArchitecture = "64-bit Excel"
#Else
  Dim osArch As String
  osArch = DetectOSArchitecture()
  If InStr(osArch, "64") > 0 Then
    DetectOfficeArchitecture = "32-bit Excel (WoW64)"
  Else
    DetectOfficeArchitecture = "32-bit Excel"
  End If
#End If
End Function

Private Function ExtractPidFromPortDescription(ByVal description As String) As String
  On Error GoTo EH
  Dim re As Object
  Set re = CreateObject("VBScript.RegExp")
  If re Is Nothing Then Exit Function
  re.Global = False
  re.IgnoreCase = True
  re.Pattern = "PID\s+(\d+)"
  If re.Test(description) Then
    ExtractPidFromPortDescription = re.Execute(description)(0).SubMatches(0)
  End If
  Exit Function
EH:
  ExtractPidFromPortDescription = ""
End Function

Private Function ExtractEndpointFromPortDescription(ByVal description As String) As String
  Dim arrowPos As Long
  arrowPos = InStr(description, "->")
  If arrowPos > 0 Then
    ExtractEndpointFromPortDescription = Trim$(Mid$(description, arrowPos + 2))
  Else
    ExtractEndpointFromPortDescription = ""
  End If
End Function

Private Function DetectExcludedRange(ByVal netshOutput As String, ByVal portNumber As Long) As String
  On Error GoTo EH
  Dim re As Object
  Set re = CreateObject("VBScript.RegExp")
  If re Is Nothing Then Exit Function
  re.Pattern = "^\s*(\d+)\s+(\d+)"
  re.IgnoreCase = True
  re.Global = False
  Dim lines() As String
  lines = Split(netshOutput, vbCrLf)
  Dim line As Variant
  For Each line In lines
    Dim trimmed As String
    trimmed = Trim$(CStr(line))
    If Len(trimmed) = 0 Then GoTo NextLine
    If re.Test(trimmed) Then
      Dim startPort As Long
      Dim endPort As Long
      startPort = CLng(re.Execute(trimmed)(0).SubMatches(0))
      endPort = CLng(re.Execute(trimmed)(0).SubMatches(1))
      If portNumber >= startPort And portNumber <= endPort Then
        DetectExcludedRange = trimmed
        Exit Function
      End If
    End If
NextLine:
  Next line
  Exit Function
EH:
  DetectExcludedRange = ""
End Function

Private Function NormalizeWhitespace(ByVal text As String) As String
  On Error GoTo EH
  Dim re As Object
  Set re = CreateObject("VBScript.RegExp")
  If re Is Nothing Then
    NormalizeWhitespace = Trim$(text)
    Exit Function
  End If
  re.Pattern = "\s+"
  re.Global = True
  NormalizeWhitespace = Trim$(re.Replace(text, " "))
  Exit Function
EH:
  NormalizeWhitespace = Trim$(text)
End Function

Private Function CollectCopilotDiagnostics() As String
  Dim report As String
  report = AppendLine(report, "[環境]")
  report = AppendLine(report, "  Excel Version: " & Application.version)
  report = AppendLine(report, "  Operating System (VBA): " & Application.OperatingSystem)
  report = AppendLine(report, "  実OSアーキテクチャ: " & DetectOSArchitecture())
  report = AppendLine(report, "  Excelアーキテクチャ: " & DetectOfficeArchitecture())
  report = AppendLine(report, "  PROCESSOR_ARCHITECTURE: " & Trim$(Environ$("PROCESSOR_ARCHITECTURE")))
  report = AppendLine(report, "  PROCESSOR_ARCHITEW6432: " & Trim$(Environ$("PROCESSOR_ARCHITEW6432")))

  report = AppendLine(report, "")
  report = AppendLine(report, "[Microsoft Edge]")
  Dim edgeVersion As String
  edgeVersion = GetInstalledEdgeVersion()
  If Len(edgeVersion) > 0 Then
    report = AppendLine(report, "  Installed Edge Version: " & edgeVersion)
  Else
    report = AppendLine(report, "  Installed Edge Version: 未検出")
  End If
  Dim diagArch As String
  diagArch = EdgeArchitectureTag()
  Dim diagDriverVersion As String
  diagDriverVersion = ResolveEdgeDriverVersion(edgeVersion, diagArch)

  report = AppendLine(report, "")
  report = AppendLine(report, "[SeleniumBasic]")
  Dim primaryPath As String
  primaryPath = CombinePath(Environ$("LOCALAPPDATA"), "SeleniumBasic")
  If Len(Trim$(primaryPath)) = 0 Then primaryPath = "(未検出)"
  report = AppendLine(report, "  Primary Path: " & primaryPath)
  report = AppendLine(report, "  Installed: " & IIf(IsSeleniumBasicInstalled(), "はい", "いいえ"))

  Dim progErr As String
  report = AppendLine(report, "  ProgID Selenium.EdgeDriver: " & DescribeProgIdStatus("Selenium.EdgeDriver", progErr))
  report = AppendLine(report, "  ProgID Selenium.WebDriver: " & DescribeProgIdStatus("Selenium.WebDriver", progErr))

  report = AppendLine(report, "")
  report = AppendLine(report, "[ネットワークチェック]")
  If Len(diagDriverVersion) > 0 Then
    Dim primaryDownloadUrl As String
    primaryDownloadUrl = "https://msedgedriver.microsoft.com/" & diagDriverVersion & "/edgedriver_" & diagArch & ".zip"
    report = AppendLine(report, "  Microsoft CDN (" & diagDriverVersion & "): " & TestHttpEndpoint(primaryDownloadUrl))
  Else
    report = AppendLine(report, "  Microsoft CDN: バージョン情報が取得できませんでした。")
  End If
  Dim latestReleaseStatus As String
  latestReleaseStatus = TestHttpEndpoint("https://msedgedriver.microsoft.com/LATEST_RELEASE")
  If InStr(1, latestReleaseStatus, "HTTP 404", vbTextCompare) > 0 Then
    report = AppendLine(report, "  Microsoft CDN (LATEST_RELEASE): 応答 404（仕様上出ることがあります）")
  Else
    report = AppendLine(report, "  Microsoft CDN (LATEST_RELEASE): " & latestReleaseStatus)
  End If
  report = AppendLine(report, "  Microsoft CDN (LATEST_STABLE): " & TestHttpEndpoint("https://msedgedriver.microsoft.com/LATEST_STABLE"))

  report = AppendLine(report, "")
  report = AppendLine(report, "[想定されるダウンロードURL]")
  If Len(diagDriverVersion) = 0 Then
    report = AppendLine(report, "  取得できませんでした。ネットワーク制限の解除後に再実行してください。")
  Else
    Dim downloadCandidates As Collection
    Set downloadCandidates = EdgeDriverDownloadUrls(diagDriverVersion, diagArch)
    Dim candidateUrl As Variant
    For Each candidateUrl In downloadCandidates
      report = AppendLine(report, "  - " & CStr(candidateUrl))
    Next candidateUrl
  End If

  Dim hadEdgeDriver As Boolean
  hadEdgeDriver = (Len(FirstExistingEdgeDriverPath()) > 0)
  Dim autoDownloadPath As String
  Dim autoDownloaded As Boolean
  autoDownloaded = False
  Dim autoDownloadFailed As Boolean
  autoDownloadFailed = False
  Dim autoDownloadError As String
  autoDownloadError = ""
  If Not hadEdgeDriver Then
    Dim ensurePath As String
    Dim ensureErr As String
    If EnsureEdgeDriver(ensurePath, ensureErr) Then
      If Len(Trim$(ensurePath)) > 0 And FileExists(ensurePath) Then
        autoDownloaded = True
        autoDownloadPath = ensurePath
      Else
        autoDownloadFailed = True
        autoDownloadError = AppendError(autoDownloadError, "msedgedriver.exe の配置を確認できませんでした。")
      End If
    Else
      autoDownloadFailed = True
      autoDownloadError = ensureErr
    End If
  End If
  If autoDownloaded Then
    report = AppendLine(report, "")
    report = AppendLine(report, "[Edge Driver 自動ダウンロード]")
    report = AppendLine(report, "  msedgedriver.exe を " & autoDownloadPath & " に取得しました。")
  ElseIf (Not hadEdgeDriver) And autoDownloadFailed Then
    report = AppendLine(report, "")
    report = AppendLine(report, "[Edge Driver 自動ダウンロード]")
    report = AppendLine(report, "  msedgedriver.exe の自動ダウンロードに失敗しました。")
    If Len(Trim$(autoDownloadError)) > 0 Then
      report = AppendLine(report, "  理由: " & Replace(autoDownloadError, vbCrLf, " / "))
    Else
      report = AppendLine(report, "  ネットワークやプロキシ設定を確認してください。")
    End If
  End If

  report = AppendLine(report, "")
  report = AppendLine(report, "[Edge Driver ファイル]")
  Dim candidates As Collection
  Set candidates = EdgeDriverCandidatePaths()
  Dim path As Variant
  Dim firstExisting As String
  firstExisting = ""
  Dim firstDriverVersion As String
  firstDriverVersion = ""
  For Each path In candidates
    Dim status As String
    Dim candidatePath As String
    candidatePath = CStr(path)
    If FileExists(candidatePath) Then
      Dim fileVersion As String
      fileVersion = GetExecutableVersion(candidatePath)
      status = "存在 (Version: " & IIf(Len(fileVersion) > 0, fileVersion, "不明") & ")"
      If Len(firstExisting) = 0 Then
        firstExisting = candidatePath
        firstDriverVersion = fileVersion
      End If
    Else
      status = "未検出"
    End If
    report = AppendLine(report, "  - " & candidatePath & " : " & status)
  Next path
  If Len(firstExisting) = 0 And autoDownloaded Then
    firstExisting = autoDownloadPath
  End If

  report = AppendLine(report, "")
  report = AppendLine(report, "[msedgedriver.exe --version テスト]")
  If Len(firstExisting) = 0 Then
    report = AppendLine(report, "  実行対象が見つかりません。")
  Else
    report = AppendLine(report, "  対象: " & firstExisting)
    report = AppendLine(report, "  結果: " & TestDriverExecutable(firstExisting))
  End If

  report = AppendLine(report, "")
  report = AppendLine(report, "[ポート待受診断]")
  Dim testPort As Long
  Dim driverPortDescriptions As Collection
  Dim detectedPort As Long
  Dim usedProbe As Boolean
  detectedPort = DetectEdgeDriverListeningPorts(driverPortDescriptions)
  If detectedPort > 0 Then
    RememberCopilotDiagPort detectedPort
    testPort = detectedPort
  Else
    testPort = SuggestEdgeDriverPort()
  End If
  If Not driverPortDescriptions Is Nothing Then
    If driverPortDescriptions.Count > 0 Then
      report = AppendLine(report, "  msedgedriver.exe の待受確認:")
      Dim desc As Variant
      For Each desc In driverPortDescriptions
        report = AppendLine(report, "    " & CStr(desc))
      Next desc
    End If
  End If

  Dim probeLogLines As Collection
  Dim probeError As String
  Dim probePort As Long
  If detectedPort = 0 And Len(firstExisting) > 0 Then
    usedProbe = True
    probePort = ProbeEdgeDriverListeningPort(firstExisting, probeLogLines, probeError)
    If probePort > 0 Then
      RememberCopilotDiagPort probePort
      testPort = probePort
      report = AppendLine(report, "  msedgedriver.exe 診断起動: 127.0.0.1:" & probePort)
    ElseIf Len(Trim$(probeError)) > 0 Then
      report = AppendLine(report, "  msedgedriver.exe 診断起動に失敗: " & probeError)
    Else
      report = AppendLine(report, "  msedgedriver.exe 診断起動: ポート情報を取得できませんでした。")
    End If
  End If
  If Not probeLogLines Is Nothing Then
    If probeLogLines.Count > 0 Then
      report = AppendLine(report, "  診断起動ログ(抜粋):")
      Dim probeLine As Variant
      For Each probeLine In probeLogLines
        report = AppendLine(report, "    " & CStr(probeLine))
      Next probeLine
    End If
  End If
  If testPort > 0 Then
    Dim normalizedEdgeVersion As String
    Dim normalizedDriverVersion As String
    normalizedEdgeVersion = NormalizeEdgeVersion(edgeVersion)
    normalizedDriverVersion = NormalizeEdgeVersion(firstDriverVersion)
    If Len(normalizedEdgeVersion) > 0 And Len(normalizedDriverVersion) > 0 Then
      If StrComp(normalizedEdgeVersion, normalizedDriverVersion, vbTextCompare) = 0 Then
        report = AppendLine(report, "  バージョン整合: OK (" & normalizedEdgeVersion & ")")
      Else
        report = AppendLine(report, "  バージョン整合: NG (Edge=" & normalizedEdgeVersion & " / Driver=" & normalizedDriverVersion & ")")
      End If
    End If
    report = AppendLine(report, "  想定ポート: 127.0.0.1:" & testPort)
    If Not usedProbe Then
      report = AppendLine(report, "  ドライバーHTTP疎通: " & TestDriverEndpoint(testPort))
      Dim portDiag As String
      On Error GoTo PortDiagFail
      portDiag = CollectPortDiagnostics(testPort)
      On Error GoTo 0
      If Len(Trim$(portDiag)) > 0 Then
        Dim portLine As Variant
        For Each portLine In Split(portDiag, vbCrLf)
          report = AppendLine(report, "  " & CStr(portLine))
        Next portLine
      Else
        report = AppendLine(report, "  ポート診断情報はありません。")
      End If
    Else
      report = AppendLine(report, "  ドライバーHTTP疎通: probe_http の結果を参照してください。")
      report = AppendLine(report, "  OSレベルの詳細診断はプローブ終了後のため省略しました。")
    End If
  Else
    report = AppendLine(report, "  想定ポートを推定できませんでした。Copilot起動ログでポート番号を確認してください。")
  End If
  GoTo PortDiagDone

PortDiagFail:
  report = AppendLine(report, "  ポート診断の実行に失敗しました: " & Err.description)
  On Error GoTo 0

PortDiagDone:
  On Error GoTo 0

  report = AppendLine(report, "")
  report = AppendLine(report, "[SeleniumBasic 経由の起動テスト]")
  If IsSeleniumBasicInstalled() Then
    If Len(firstExisting) = 0 Then
      report = AppendLine(report, "  結果: msedgedriver.exe が見つからないためスキップしました。")
    Else
      Dim seleniumLines As Collection
      Dim seleniumErr As String
      If RunSeleniumBasicDriverProbe(firstExisting, seleniumLines, seleniumErr) Then
        report = AppendLine(report, "  結果: 成功 (SeleniumBasic から Edge ドライバーを起動できました)")
      Else
        report = AppendLine(report, "  結果: 失敗")
        If Len(Trim$(seleniumErr)) > 0 Then
          report = AppendLine(report, "  理由: " & Replace(seleniumErr, vbCrLf, " / "))
        End If
      End If
      If Not seleniumLines Is Nothing Then
        Dim seleniumLine As Variant
        For Each seleniumLine In seleniumLines
          report = AppendLine(report, "  " & CStr(seleniumLine))
        Next seleniumLine
      End If
    End If
  Else
    report = AppendLine(report, "  結果: SeleniumBasic が未インストールのためスキップしました。")
  End If

  CollectCopilotDiagnostics = report
End Function

Private Function TestHttpEndpoint(ByVal url As String) As String
  Dim status As String
  If ProbeHttpEndpoint(url, status) Then
    TestHttpEndpoint = "成功 (" & status & ")"
  Else
    TestHttpEndpoint = "失敗 (" & status & ")"
  End If
End Function

Private Function ProbeHttpEndpoint(ByVal url As String, ByRef statusOut As String) As Boolean
  On Error GoTo EH
  Dim req As Object
  Set req = CreateHttpRequest()
  If req Is Nothing Then
    statusOut = "HTTP クライアント初期化に失敗"
    Exit Function
  End If
  req.Open "GET", url, False
  On Error Resume Next
  req.setRequestHeader "User-Agent", "ECMTranslator/1.0"
  On Error GoTo EH
  req.Send
  Dim statusCode As Long
  Dim statusText As String
  statusCode = 0
  statusText = ""
  On Error Resume Next
  statusCode = req.status
  statusText = req.statusText
  On Error GoTo EH
  statusOut = "HTTP " & statusCode & IIf(Len(statusText) > 0, " " & statusText, "")
  ProbeHttpEndpoint = (statusCode >= 200 And statusCode < 400)
  Exit Function
EH:
  statusOut = "エラー: " & Err.Number & " " & Err.description
End Function

Private Function HttpResourceExists(ByVal url As String) As Boolean
  On Error GoTo EH
  Dim req As Object
  Set req = CreateHttpRequest()
  If req Is Nothing Then Exit Function
  req.Open "HEAD", url, False
  On Error Resume Next
  req.Send
  Dim statusCode As Long
  statusCode = 0
  statusCode = req.status
  On Error GoTo EH
  If statusCode = 405 Or statusCode = 501 Then
    req.Open "GET", url, False
    req.setRequestHeader "Range", "bytes=0-0"
    On Error Resume Next
    req.Send
    statusCode = req.status
    On Error GoTo EH
  End If
  HttpResourceExists = (statusCode >= 200 And statusCode < 400)
  Exit Function
EH:
  HttpResourceExists = False
End Function

Private Function DescribeProgIdStatus(ByVal progId As String, ByRef errMsg As String) As String
  Dim ok As Boolean
  ok = CanCreateProgId(progId, errMsg)
  If ok Then
    DescribeProgIdStatus = "利用可能"
  Else
    DescribeProgIdStatus = "利用不可 (" & errMsg & ")"
  End If
End Function

Private Function EdgeDriverCandidatePaths() As Collection
  Dim list As Collection
  Set list = New Collection
  AddUniquePath list, CombinePath(DriverStorageRoot(), "edge\msedgedriver.exe")
  Dim base As Variant
  For Each base In Array(Environ$("LOCALAPPDATA"), Environ$("APPDATA"), Environ$("PROGRAMFILES"), Environ$("PROGRAMFILES(X86)"))
    Dim baseStr As String
    baseStr = Trim$(CStr(base))
    If Len(baseStr) > 0 Then
      AddUniquePath list, CombinePath(baseStr, "SeleniumBasic\drivers\msedgedriver.exe")
      AddUniquePath list, CombinePath(baseStr, "SeleniumBasic\msedgedriver.exe")
    End If
  Next base
  Set EdgeDriverCandidatePaths = list
End Function

Private Function FirstExistingEdgeDriverPath() As String
  Dim candidates As Collection
  Set candidates = EdgeDriverCandidatePaths()
  Dim candidate As Variant
  For Each candidate In candidates
    Dim candidatePath As String
    candidatePath = CStr(candidate)
    If FileExists(candidatePath) Then
      FirstExistingEdgeDriverPath = candidatePath
      Exit Function
    End If
  Next candidate
End Function

Private Sub AddUniquePath(ByVal list As Collection, ByVal newPath As String)
  Dim normalized As String
  normalized = Trim$(CStr(newPath))
  If Len(normalized) = 0 Then Exit Sub
  Dim item As Variant
  For Each item In list
    If StrComp(CStr(item), normalized, vbTextCompare) = 0 Then Exit Sub
  Next item
  list.Add normalized
End Sub

Private Function TestDriverExecutable(ByVal driverPath As String) As String
  On Error GoTo EH
  Dim shell As Object
  Set shell = CreateObject("WScript.Shell")
  Dim cmd As String
  cmd = """" & driverPath & """ --version"
  Dim exec As Object
  Set exec = shell.exec(cmd)
  Dim startTick As Double
  startTick = Timer
  Do While exec.status = 0
    If SecondsElapsed(startTick) > 5 Then
      exec.Terminate
      TestDriverExecutable = "タイムアウト (--version が 5 秒以内に終了しませんでした)"
      Exit Function
    End If
    DoEvents
  Loop
  Dim output As String
  output = Trim$(exec.stdout.ReadAll)
  Dim errText As String
  errText = Trim$(exec.stderr.ReadAll)
  If Len(output) > 0 Then
    TestDriverExecutable = "成功: " & output
  ElseIf Len(errText) > 0 Then
    TestDriverExecutable = "エラー: " & errText
  Else
    If exec.exitCode = 0 Then
      TestDriverExecutable = "成功 (出力なし)"
    Else
      TestDriverExecutable = "終了コード " & exec.exitCode
    End If
  End If
  Exit Function
EH:
  TestDriverExecutable = "実行失敗: " & Err.Number & " " & Err.description
End Function

Private Function CanCreateProgId(ByVal progId As String, ByRef errMsg As String) As Boolean
  On Error GoTo EH
  Dim obj As Object
  Set obj = CreateObject(progId)
  CanCreateProgId = Not obj Is Nothing
  On Error Resume Next
  If Not obj Is Nothing Then
    obj.Quit
    Set obj = Nothing
  End If
  On Error GoTo 0
  errMsg = ""
  Exit Function
EH:
  errMsg = Err.Number & " " & Err.description
  CanCreateProgId = False
  Err.Clear
End Function

Private Function WaitForCopilotReady(ByVal driver As Object, ByVal targetUrl As String, ByVal timeoutSeconds As Long, ByRef reasonOut As String) As Boolean
  reasonOut = ""
  If driver Is Nothing Then
    reasonOut = "WebDriver セッションが初期化されていません。"
    Exit Function
  End If
  Dim startTick As Double
  startTick = Timer
  Dim targetCheck As String
  targetCheck = LCase$(Trim$(targetUrl))
  If Len(targetCheck) = 0 Then targetCheck = "https://m365.cloud.microsoft/chat/"

  Dim lastUrl As String
  Dim lastStatus As String
  Dim blankSince As Double
  blankSince = startTick
  lastUrl = ""
  lastStatus = ""

  Do
    Dim currentUrl As String
    currentUrl = ""
    Dim lowerUrl As String
    Dim errNum As Long
    Dim errDesc As String

    On Error Resume Next
    currentUrl = driver.url
    errNum = Err.Number
    errDesc = Err.description
    Err.Clear
    On Error GoTo 0

    If errNum <> 0 Then
      reasonOut = DescribeBrowserNavigationError(errDesc)
      SetStatus reasonOut
      Exit Function
    End If

    If Len(currentUrl) > 0 Then
      lowerUrl = LCase$(currentUrl)
      Dim statusMsg As String
      statusMsg = ""
      If currentUrl <> lastUrl Then
        lastUrl = currentUrl
        statusMsg = "Copilotブラウザでページを読み込み中: " & TruncateStatus(currentUrl)
      End If
      If InStr(lowerUrl, "m365.cloud.microsoft/chat") > 0 _
         Or InStr(lowerUrl, targetCheck) > 0 Then
        WaitForCopilotReady = True
        Exit Function
      End If
      If InStr(lowerUrl, "login.microsoftonline.com") > 0 Then
        statusMsg = "Microsoft 365 のサインイン待機中です。ブラウザでサインインしてください。"
      ElseIf InStr(lowerUrl, "aadcdn.msauth.net") > 0 Or InStr(lowerUrl, "microsoft.com") > 0 Then
        statusMsg = "認証ページを読み込み中です。数分待っても変化しなければネットワークを確認してください。"
      End If
      If Len(statusMsg) > 0 Then
        If statusMsg <> lastStatus Then
          lastStatus = statusMsg
          SetStatus statusMsg
        End If
      End If
      blankSince = Timer
    Else
      Dim blankMsg As String
      blankMsg = ""
      If SecondsElapsed(blankSince) > 20 Then
        blankMsg = "ブラウザがページを開けていません。ドライバーまたはネットワークを確認してください。"
      ElseIf SecondsElapsed(startTick) > 5 Then
        blankMsg = "Copilotブラウザの起動を待機しています..."
      End If
      If Len(blankMsg) > 0 Then
        If blankMsg <> lastStatus Then
          lastStatus = blankMsg
          SetStatus blankMsg
        End If
      End If
    End If

    If TimeoutElapsed(startTick, timeoutSeconds) Then Exit Do
    PauseWithDoEvents 1
  Loop

  If Len(reasonOut) = 0 Then
    If Len(lastUrl) > 0 Then
      lowerUrl = LCase$(lastUrl)
      If InStr(lowerUrl, "login.microsoftonline.com") > 0 Then
        reasonOut = "Microsoft アカウントのサインインが完了していません。ブラウザで資格情報を入力してください。"
      ElseIf InStr(lowerUrl, "microsoft.com") > 0 Then
        reasonOut = "認証ページで処理が止まっています。ネットワーク制限やポップアップブロックを確認してください。"
      Else
        reasonOut = "ブラウザが """ & lastUrl & """ を表示した状態で停止しました。"
      End If
    Else
      reasonOut = "ブラウザが about:blank から遷移できませんでした。ドライバー更新やネットワーク接続を確認してください。"
    End If
  End If
End Function

Private Function TimeoutElapsed(ByVal startTick As Double, ByVal timeoutSeconds As Long) As Boolean
  Dim nowTick As Double
  nowTick = Timer

  Dim elapsed As Double
  elapsed = nowTick - startTick
  If elapsed < 0 Then elapsed = elapsed + 86400#

  TimeoutElapsed = (elapsed >= timeoutSeconds)
End Function

Private Function SecondsElapsed(ByVal sinceTick As Double) As Double
  Dim nowTick As Double
  nowTick = Timer
  Dim delta As Double
  delta = nowTick - sinceTick
  If delta < 0 Then delta = delta + 86400#
  SecondsElapsed = delta
End Function

Private Function TruncateStatus(ByVal text As String) As String
  Const MAX_LEN As Long = 110
  If Len(text) <= MAX_LEN Then
    TruncateStatus = text
  Else
    TruncateStatus = Left$(text, MAX_LEN - 3) & "..."
  End If
End Function

Private Function DescribeBrowserNavigationError(ByVal errDesc As String) As String
  Dim baseMsg As String
  baseMsg = "ブラウザの現在地を取得できませんでした: " & errDesc
  Dim hint As String
  Dim lower As String
  lower = LCase$(errDesc)
  If InStr(lower, "browsernotstarted") > 0 Then
    hint = "ブラウザプロセスが起動していない可能性があります。SeleniumBasic が Edge ドライバーを認識しているか確認し、" & _
           "C:\Users\<ユーザー名>\AppData\Local\SeleniumBasic\drivers\ に msedgedriver.exe が配置されているか確認してください。"
  ElseIf InStr(lower, "disconnected") > 0 Then
    hint = "WebDriver セッションが途中で切断されました。ウイルス対策ソフトやグループポリシーがブラウザ起動を阻害していないか確認してください。"
  ElseIf InStr(lower, "timeout") > 0 Then
    hint = "ブラウザの起動がタイムアウトしました。Edge ドライバーのバージョンが Edge 本体と一致しているか確認してください。"
  End If
  If Len(hint) > 0 Then
    DescribeBrowserNavigationError = baseMsg & vbCrLf & hint
  Else
    DescribeBrowserNavigationError = baseMsg
  End If
End Function

Private Sub PauseWithDoEvents(ByVal seconds As Double)
  If seconds <= 0 Then
    DoEvents
    Exit Sub
  End If
  Dim waitUntil As Date
  waitUntil = DateAdd("s", seconds, Now)
  DoEvents
  On Error Resume Next
  Application.Wait waitUntil
  On Error GoTo 0
End Sub

'========================
'  ドライバーセットアップ
'========================
Private Function EnsureBrowserDriver(ByVal browser As String, ByRef driverPathOut As String, Optional ByRef errorOut As String) As Boolean
  On Error GoTo EH
  errorOut = ""
  Dim pathOut As String
  Select Case LCase$(browser)
    Case "edge"
      If EnsureEdgeDriver(pathOut, errorOut) Then
        driverPathOut = pathOut
        EnsureBrowserDriver = True
      End If
    Case "chrome"
      Dim chromeErr As String
      If EnsureChromeDriver(pathOut, chromeErr) Then
        driverPathOut = pathOut
        EnsureBrowserDriver = True
      Else
        errorOut = chromeErr
      End If
  End Select
  Exit Function
EH:
  ' 失敗しても既存環境のドライバー検出に任せる
  errorOut = "ドライバー準備中に例外が発生しました: " & Err.Number & " " & Err.description
  EnsureBrowserDriver = False
End Function

Private Function EnsureEdgeDriver(ByRef driverPathOut As String, Optional ByRef errorOut As String) As Boolean
  errorOut = ""
  Dim storageRoot As String
  storageRoot = CombinePath(DriverStorageRoot(), "edge")
  If Not EnsureFolderExists(storageRoot) Then
    errorOut = "Edgeドライバー保存先フォルダーを作成できませんでした: " & storageRoot
    Exit Function
  End If

  Dim driverExe As String
  driverExe = CombinePath(storageRoot, "msedgedriver.exe")

  Dim edgeVersion As String
  edgeVersion = GetInstalledEdgeVersion()
  Dim normalizedEdgeVersion As String
  normalizedEdgeVersion = NormalizeEdgeVersion(edgeVersion)
  Dim archTag As String
  archTag = EdgeArchitectureTag()
  If FileExists(driverExe) Then
    Dim existingVersion As String
    Dim normalizedExisting As String
    existingVersion = GetExecutableVersion(driverExe)
    normalizedExisting = NormalizeEdgeVersion(existingVersion)
    Dim versionsMatch As Boolean
    versionsMatch = False
    If Len(normalizedEdgeVersion) > 0 And Len(normalizedExisting) > 0 Then
      versionsMatch = (StrComp(normalizedEdgeVersion, normalizedExisting, vbTextCompare) = 0)
    End If
    If versionsMatch Then
      driverPathOut = driverExe
      EnsureEdgeDriver = True
      RegisterDriverForSeleniumBasic driverExe
      Exit Function
    End If
    If IsEdgeDriverCompatible(driverExe, edgeVersion) And Not versionsMatch Then
      SetStatus "Edgeドライバーを更新しています... (Edge: " & IIf(Len(normalizedEdgeVersion) > 0, normalizedEdgeVersion, "不明") & " / Driver: " & IIf(Len(normalizedExisting) > 0, normalizedExisting, "不明") & ")"
    Else
      SetStatus "Edgeドライバーを更新しています..."
    End If
    DeleteFileSafe driverExe
    ClearFolderContents storageRoot
  End If

  SetStatus "Edgeドライバーを自動セットアップ中..."

  Dim driverVersion As String
  driverVersion = ResolveEdgeDriverVersion(edgeVersion, archTag)
  If Len(driverVersion) = 0 Then
    SetStatus "Edgeドライバーのバージョン取得に失敗しました。"
    errorOut = "Edgeドライバーのバージョン取得に失敗しました。Edge バージョン: " & IIf(Len(edgeVersion) > 0, edgeVersion, "未検出")
    Exit Function
  End If

  Dim tempZip As String
  tempZip = CreateTempFile("edge_driver_", ".zip")
  If Len(tempZip) = 0 Then
    errorOut = "Edgeドライバー展開用の一時ファイルを作成できませんでした。"
    Exit Function
  End If

  Dim downloaded As Boolean
  downloaded = False
  Dim url As Variant
  Dim candidates As Collection
  Set candidates = EdgeDriverDownloadUrls(driverVersion, archTag)
  Dim downloadErr As String
  Dim lastDownloadError As String
  lastDownloadError = ""
  For Each url In candidates
    If DownloadBinaryFile(CStr(url), tempZip, downloadErr) Then
      downloaded = True
      Exit For
    Else
      If Len(Trim$(downloadErr)) > 0 Then
        lastDownloadError = AppendError(lastDownloadError, CStr(url) & " -> " & downloadErr)
      Else
        lastDownloadError = AppendError(lastDownloadError, CStr(url) & " -> 不明なエラー")
      End If
      DeleteFileSafe tempZip
    End If
  Next url

  If Not downloaded Then
    SetStatus "Edgeドライバーのダウンロードに失敗しました。"
    DeleteFileSafe tempZip
    If Len(lastDownloadError) > 0 Then
      errorOut = "Edgeドライバーのダウンロードに失敗しました。" & vbCrLf & lastDownloadError
    Else
      errorOut = "Edgeドライバーのダウンロードに失敗しました。ネットワーク制限やプロキシ設定を確認してください。"
    End If
    Exit Function
  End If

  ClearFolderContents storageRoot
  Dim extractErr As String
  If Not ExtractZipFile(tempZip, storageRoot, extractErr) Then
    SetStatus "Edgeドライバーの展開に失敗しました。"
    DeleteFileSafe tempZip
    If Len(Trim$(extractErr)) > 0 Then
      errorOut = "Edgeドライバーの展開に失敗しました。" & vbCrLf & extractErr
    Else
      errorOut = "Edgeドライバーの展開に失敗しました。Zip フォルダー機能やアクセス権を確認してください。"
    End If
    Exit Function
  End If
  DeleteFileSafe tempZip

  Dim found As String
  found = FindFileRecursive(storageRoot, "msedgedriver.exe")
  If Len(found) = 0 Then
    errorOut = "展開後に msedgedriver.exe が見つかりませんでした。ZIP の内容を確認してください。"
    Exit Function
  End If

  If LCase$(found) <> LCase$(driverExe) Then
    On Error Resume Next
    CreateObject("Scripting.FileSystemObject").CopyFile found, driverExe, True
    On Error GoTo 0
  End If

  If FileExists(driverExe) Then
    Dim downloadedVersion As String
    Dim normalizedDownloaded As String
    downloadedVersion = GetExecutableVersion(driverExe)
    normalizedDownloaded = NormalizeEdgeVersion(downloadedVersion)
    If Len(normalizedEdgeVersion) > 0 And Len(normalizedDownloaded) > 0 Then
      If StrComp(normalizedEdgeVersion, normalizedDownloaded, vbTextCompare) <> 0 Then
        errorOut = "ダウンロードした Edge ドライバーのバージョン (" & normalizedDownloaded & ") が Edge (" & normalizedEdgeVersion & ") と一致しません。"
        DeleteFileSafe driverExe
        ClearFolderContents storageRoot
        Exit Function
      End If
    End If
    driverPathOut = driverExe
    EnsureEdgeDriver = True
    RegisterDriverForSeleniumBasic driverExe
    SetStatus "Edgeドライバーの準備が完了しました。"
    errorOut = ""
  Else
    errorOut = "msedgedriver.exe の配置に失敗しました。"
  End If
End Function

Private Function EnsureChromeDriver(ByRef driverPathOut As String, Optional ByRef errorOut As String) As Boolean
  errorOut = ""
  Dim storageRoot As String
  storageRoot = CombinePath(DriverStorageRoot(), "chrome")
  If Not EnsureFolderExists(storageRoot) Then
    errorOut = "Chromeドライバー保存先フォルダーを作成できませんでした: " & storageRoot
    Exit Function
  End If

  Dim driverExe As String
  driverExe = CombinePath(storageRoot, "chromedriver.exe")
  If FileExists(driverExe) Then
    driverPathOut = driverExe
    EnsureChromeDriver = True
    RegisterDriverForSeleniumBasic driverExe
    Exit Function
  End If

  SetStatus "Chromeドライバーを自動セットアップ中..."

  Dim chromeVersion As String
  chromeVersion = GetInstalledChromeVersion()
  Dim driverVersion As String
  driverVersion = GetLatestChromeDriverVersion(chromeVersion)
  If Len(driverVersion) = 0 Then
    SetStatus "Chromeドライバーのバージョン取得に失敗しました。"
    errorOut = "Chromeドライバーのバージョン取得に失敗しました。Chrome バージョン: " & IIf(Len(chromeVersion) > 0, chromeVersion, "未検出")
    Exit Function
  End If

  Dim downloadUrl As String
  downloadUrl = "https://chromedriver.storage.googleapis.com/" & driverVersion & "/chromedriver_win32.zip"

  Dim tempZip As String
  tempZip = CreateTempFile("chrome_driver_", ".zip")
  If Len(tempZip) = 0 Then
    errorOut = "Chromeドライバー展開用の一時ファイルを作成できませんでした。"
    Exit Function
  End If

  Dim chromeDownloadErr As String
  If Not DownloadBinaryFile(downloadUrl, tempZip, chromeDownloadErr) Then
    SetStatus "Chromeドライバーのダウンロードに失敗しました。"
    DeleteFileSafe tempZip
    If Len(Trim$(chromeDownloadErr)) > 0 Then
      errorOut = "Chromeドライバーのダウンロードに失敗しました。" & vbCrLf & chromeDownloadErr
    Else
      errorOut = "Chromeドライバーのダウンロードに失敗しました。ネットワーク設定を確認してください。"
    End If
    Exit Function
  End If

  Dim chromeExtractErr As String
  If Not ExtractZipFile(tempZip, storageRoot, chromeExtractErr) Then
    SetStatus "Chromeドライバーの展開に失敗しました。"
    DeleteFileSafe tempZip
    If Len(Trim$(chromeExtractErr)) > 0 Then
      errorOut = "Chromeドライバーの展開に失敗しました。" & vbCrLf & chromeExtractErr
    Else
      errorOut = "Chromeドライバーの展開に失敗しました。Zip フォルダー機能やアクセス権を確認してください。"
    End If
    Exit Function
  End If
  DeleteFileSafe tempZip

  Dim found As String
  found = FindFileRecursive(storageRoot, "chromedriver.exe")
  If Len(found) = 0 Then
    errorOut = "展開後に chromedriver.exe が見つかりませんでした。ZIP の内容を確認してください。"
    Exit Function
  End If

  If LCase$(found) <> LCase$(driverExe) Then
    On Error Resume Next
    CreateObject("Scripting.FileSystemObject").CopyFile found, driverExe, True
    On Error GoTo 0
  End If

  If FileExists(driverExe) Then
    driverPathOut = driverExe
    EnsureChromeDriver = True
    RegisterDriverForSeleniumBasic driverExe
    SetStatus "Chromeドライバーの準備が完了しました。"
    errorOut = ""
  Else
    errorOut = "chromedriver.exe の配置に失敗しました。"
  End If
End Function

Private Function DriverStorageRoot() As String
  Dim basePaths As Variant
  basePaths = Array(Environ$("LOCALAPPDATA"), Environ$("APPDATA"), Environ$("USERPROFILE"), Environ$("TEMP"), ThisWorkbook.path, "C:\Temp")

  Dim base As Variant
  For Each base In basePaths
    Dim baseStr As String
    baseStr = Trim$(CStr(base))
    If Len(baseStr) = 0 Then GoTo NextBase
    Dim candidate As String
    candidate = CombinePath(baseStr, "ECMDrivers")
    If EnsureFolderExists(candidate) Then
      DriverStorageRoot = candidate
      Exit Function
    End If
NextBase:
  Next base

  Dim fallback As String
  fallback = "C:\Temp\ECMDrivers"
  Call EnsureFolderExists(fallback)
  DriverStorageRoot = fallback
End Function

Private Function EnsureFolderExists(ByVal folderPath As String) As Boolean
  Dim fso As Object
  Set fso = CreateObject("Scripting.FileSystemObject")
  On Error Resume Next
  If fso.FolderExists(folderPath) Then
    EnsureFolderExists = True
  Else
    fso.CreateFolder folderPath
    EnsureFolderExists = fso.FolderExists(folderPath)
  End If
  On Error GoTo 0
End Function

Private Function CombinePath(ByVal basePath As String, ByVal appendPath As String) As String
  If Len(basePath) = 0 Then
    CombinePath = appendPath
    Exit Function
  End If
  If Len(appendPath) = 0 Then
    CombinePath = basePath
    Exit Function
  End If

  Dim sep As String
  sep = Application.PathSeparator
  If Right$(basePath, 1) = sep Then
    If Left$(appendPath, 1) = sep Then
      CombinePath = basePath & Mid$(appendPath, 2)
    Else
      CombinePath = basePath & appendPath
    End If
  Else
    If Left$(appendPath, 1) = sep Then
      CombinePath = basePath & appendPath
    Else
      CombinePath = basePath & sep & appendPath
    End If
  End If
End Function

Private Function FileExists(ByVal filePath As String) As Boolean
  On Error Resume Next
  FileExists = (Len(Dir$(filePath, vbNormal)) > 0)
  On Error GoTo 0
End Function

Private Function IsZipFile(ByVal filePath As String) As Boolean
  On Error GoTo EH
  If Len(filePath) = 0 Then Exit Function
  If Not FileExists(filePath) Then Exit Function
  Dim fso As Object
  Set fso = CreateObject("Scripting.FileSystemObject")
  Dim fileObj As Object
  Set fileObj = fso.GetFile(filePath)
  If (fileObj.Attributes And vbDirectory) = vbDirectory Then Exit Function
  Dim stm As Object
  Set stm = CreateObject("ADODB.Stream")
  stm.Type = 1
  stm.Open
  stm.LoadFromFile filePath
  If stm.size < 4 Then GoTo Cleanup
  stm.Position = 0
  Dim buffer() As Byte
  buffer = stm.Read(4)
  If UBound(buffer) >= 1 Then
    If buffer(0) = &H50 And buffer(1) = &H4B Then ' "PK"
      IsZipFile = True
    End If
  End If
Cleanup:
  stm.Close
  Exit Function
EH:
  IsZipFile = False
End Function

Private Function DownloadBinaryFile(ByVal url As String, ByVal destPath As String, Optional ByRef errorOut As String) As Boolean
  On Error GoTo EH
  errorOut = ""
  Dim req As Object
  Set req = CreateHttpRequest()
  If req Is Nothing Then
    errorOut = "HTTP クライアントの初期化に失敗しました。"
    Exit Function
  End If
  req.Open "GET", url, False
  On Error Resume Next
  req.setRequestHeader "User-Agent", "ECMTranslator/1.0"
  req.setRequestHeader "Accept", "application/octet-stream, application/zip;q=0.9, */*;q=0.1"
  On Error GoTo EH
  req.Send
  Dim statusCode As Long
  Dim statusText As String
  On Error Resume Next
  statusCode = req.status
  statusText = req.statusText
  On Error GoTo EH
  If statusCode < 200 Or statusCode >= 300 Then
    errorOut = "HTTP " & statusCode & IIf(Len(statusText) > 0, " " & statusText, "")
    GoTo EH
  End If

  Dim responseBody As Variant
  responseBody = req.responseBody
  Dim stm As Object
  Set stm = CreateObject("ADODB.Stream")
  stm.Type = 1
  stm.Open
  stm.Write responseBody
  stm.SaveToFile destPath, 2
  stm.Close
  If Not IsZipFile(destPath) Then
    DeleteFileSafe destPath
    errorOut = "ZIP 形式ではない応答が返されました。"
    GoTo EH
  End If
  errorOut = ""
  DownloadBinaryFile = True
  Exit Function
EH:
  If Len(errorOut) = 0 Then
    errorOut = "通信エラー: " & Err.Number & " " & Err.description
  End If
  DownloadBinaryFile = False
End Function

Private Function DownloadTextFile(ByVal url As String) As String
  On Error GoTo EH
  Dim req As Object
  Set req = CreateHttpRequest()
  If req Is Nothing Then Exit Function
  req.Open "GET", url, False
  On Error Resume Next
  req.setRequestHeader "User-Agent", "ECMTranslator/1.0"
  On Error GoTo EH
  req.Send
  If req.status < 200 Or req.status >= 300 Then GoTo EH
  Dim rawText As String
  rawText = CStr(req.responseText) & ""
  DownloadTextFile = NormalizeHttpText(rawText)
  Exit Function
EH:
  DownloadTextFile = ""
End Function

Private Function NormalizeHttpText(ByVal value As String) As String
  Dim cleaned As String
  cleaned = CStr(value)
  cleaned = Replace(cleaned, vbCr, "")
  cleaned = Replace(cleaned, vbLf, "")
  cleaned = Replace(cleaned, vbNullChar, "")
  cleaned = Replace(cleaned, ChrW$(&HFEFF), "")
  cleaned = Replace(cleaned, ChrW$(&HFFFE), "")
  NormalizeHttpText = Trim$(cleaned)
End Function

Private Function VersionCompare(ByVal v1 As String, ByVal v2 As String) As Long
  Dim parts1() As String
  Dim parts2() As String
  parts1 = Split(v1, ".")
  parts2 = Split(v2, ".")
  Dim i As Long
  Dim maxLen As Long
  If UBound(parts1) > UBound(parts2) Then
    maxLen = UBound(parts1)
  Else
    maxLen = UBound(parts2)
  End If
  For i = 0 To maxLen
    Dim p1 As Long
    Dim p2 As Long
    If i <= UBound(parts1) Then p1 = Val(parts1(i)) Else p1 = 0
    If i <= UBound(parts2) Then p2 = Val(parts2(i)) Else p2 = 0
    If p1 < p2 Then
      VersionCompare = -1
      Exit Function
    ElseIf p1 > p2 Then
      VersionCompare = 1
      Exit Function
    End If
  Next i
  VersionCompare = 0
End Function

Private Function CreateHttpRequest() As Object
  On Error GoTo EH
  Dim req As Object

  Set req = CreateObject("WinHttp.WinHttpRequest.5.1")
  If Not req Is Nothing Then
    On Error Resume Next
    req.Option(6) = True ' WinHttpRequestOption_EnableRedirects
    req.Option(9) = SECURE_PROTOCOL_TLS1 Or SECURE_PROTOCOL_TLS1_1 Or SECURE_PROTOCOL_TLS1_2
    req.setTimeouts 30000, 30000, 30000, 30000
    On Error GoTo 0
    Set CreateHttpRequest = req
    Exit Function
  End If

  Err.Clear
  Set req = CreateObject("MSXML2.ServerXMLHTTP.6.0")
  If Not req Is Nothing Then
    On Error Resume Next
    req.setTimeouts 30000, 30000, 30000, 30000
    On Error GoTo 0
    Set CreateHttpRequest = req
    Exit Function
  End If

  Err.Clear
  Set req = CreateObject("MSXML2.XMLHTTP.6.0")
  If Not req Is Nothing Then
    On Error Resume Next
    req.setTimeouts 30000, 30000, 30000, 30000
    req.setRequestHeader "User-Agent", "ECMTranslator/1.0"
    On Error GoTo 0
    Set CreateHttpRequest = req
    Exit Function
  End If

  Err.Clear
  Set req = CreateObject("MSXML2.XMLHTTP")
  If Not req Is Nothing Then
    Set CreateHttpRequest = req
    Exit Function
  End If

EH:
  Set CreateHttpRequest = Nothing
End Function

Private Function ExtractZipFile(ByVal zipPath As String, ByVal targetDir As String, Optional ByRef errorOut As String) As Boolean
  errorOut = ""
  If Len(zipPath) = 0 Or Len(targetDir) = 0 Then
    errorOut = "ZIP ファイルまたは展開先のパスが空です。"
    Exit Function
  End If
  If Not FileExists(zipPath) Then
    errorOut = "ZIP ファイルが存在しません: " & zipPath
    Exit Function
  End If
  If Not EnsureFolderExists(targetDir) Then
    errorOut = "展開先フォルダーを作成できませんでした: " & targetDir
    Exit Function
  End If

  Dim shellErr As String
  shellErr = ""
  If ExtractZipWithShell(zipPath, targetDir, shellErr) Then
    If FolderHasContent(targetDir) Then
      ExtractZipFile = True
      Exit Function
    End If
  End If

  Dim psErr As String
  psErr = ""
  If ExtractZipWithPowerShell(zipPath, targetDir, psErr) Then
    If FolderHasContent(targetDir) Then
      ExtractZipFile = True
      Exit Function
    End If
  End If

  errorOut = ""
  If Len(shellErr) > 0 Then errorOut = AppendError(errorOut, shellErr)
  If Len(psErr) > 0 Then errorOut = AppendError(errorOut, psErr)
  If Len(errorOut) = 0 Then
    errorOut = "ZIP の展開に失敗しました。ZIP ファイルの内容とアクセス許可を確認してください。"
  End If
End Function

Private Function ExtractZipWithShell(ByVal zipPath As String, ByVal targetDir As String, ByRef errOut As String) As Boolean
  On Error GoTo EH
  errOut = ""
  Dim shellApp As Object
  Set shellApp = CreateObject("Shell.Application")
  If shellApp Is Nothing Then
    errOut = "Shell.Application を初期化できませんでした。"
    Exit Function
  End If
  Dim zipNs As Object, targetNs As Object
  Set zipNs = shellApp.Namespace(zipPath)
  Set targetNs = shellApp.Namespace(targetDir)
  If zipNs Is Nothing Then
    errOut = "ZIP を開くことができませんでした。ZIP ファイルが破損している可能性があります。"
    Exit Function
  End If
  If targetNs Is Nothing Then
    errOut = "展開先フォルダーを開くことができませんでした。アクセス許可を確認してください。"
    Exit Function
  End If

  targetNs.CopyHere zipNs.Items, 16 Or 256
  Dim waitUntil As Date
  waitUntil = DateAdd("s", 10, Now)
  Do
    DoEvents
    If Now >= waitUntil Then Exit Do
  Loop

  ExtractZipWithShell = True
  Exit Function
EH:
  errOut = "Shell 展開中にエラーが発生しました: " & Err.Number & " " & Err.description
  ExtractZipWithShell = False
End Function

Private Function ExtractZipWithPowerShell(ByVal zipPath As String, ByVal targetDir As String, ByRef errOut As String) As Boolean
  On Error GoTo EH
  errOut = ""
  Dim quotedZip As String
  Dim quotedDest As String
  quotedZip = """" & Replace(zipPath, """", """""") & """"
  quotedDest = """" & Replace(targetDir, """", """""") & """"
  Dim command As String
  command = "powershell -NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command ""Expand-Archive -LiteralPath " & quotedZip & " -DestinationPath " & quotedDest & " -Force"""

  Dim psOut As String
  Dim psErr As String
  Dim psExit As Long
  If Not ExecuteCommand(command, psOut, psErr, 120, psExit) Then
    If Len(Trim$(psErr)) = 0 Then psErr = "ExitCode=" & CStr(psExit)
    errOut = "PowerShell 展開でエラーが発生しました: " & psErr
    Exit Function
  End If
  ExtractZipWithPowerShell = True
  Exit Function
EH:
  errOut = "PowerShell 展開中に例外が発生しました: " & Err.Number & " " & Err.description
  ExtractZipWithPowerShell = False
End Function

Private Function FolderHasContent(ByVal folderPath As String) As Boolean
  On Error GoTo EH
  Dim fso As Object
  Set fso = CreateObject("Scripting.FileSystemObject")
  If Not fso.FolderExists(folderPath) Then Exit Function
  Dim folder As Object
  Set folder = fso.GetFolder(folderPath)
  If folder.Files.Count > 0 Or folder.SubFolders.Count > 0 Then
    FolderHasContent = True
  End If
  Exit Function
EH:
  FolderHasContent = False
End Function

Private Function FindFileRecursive(ByVal rootDir As String, ByVal fileName As String) As String
  On Error GoTo EH
  Dim fso As Object
  Set fso = CreateObject("Scripting.FileSystemObject")
  If Not fso.FolderExists(rootDir) Then Exit Function
  Dim folder As Object
  Set folder = fso.GetFolder(rootDir)
  Dim fileItem As Object
  For Each fileItem In folder.Files
    If LCase$(fileItem.Name) = LCase$(fileName) Then
      FindFileRecursive = fileItem.path
      Exit Function
    End If
  Next fileItem
  Dim subFolder As Object
  For Each subFolder In folder.SubFolders
    FindFileRecursive = FindFileRecursive(subFolder.path, fileName)
    If Len(FindFileRecursive) > 0 Then Exit Function
  Next subFolder
  Exit Function
EH:
  FindFileRecursive = ""
End Function

Private Function CreateTempFile(ByVal prefix As String, ByVal suffix As String) As String
  On Error GoTo EH
  Dim tempPath As String
  tempPath = Environ$("TEMP")
  If Len(tempPath) = 0 Then tempPath = Environ$("TMP")
  If Len(tempPath) = 0 Then tempPath = "C:\Temp"
  Dim fso As Object
  Set fso = CreateObject("Scripting.FileSystemObject")
  If Right$(tempPath, 1) <> "\" Then tempPath = tempPath & "\"
  Dim tempName As String
  tempName = prefix & fso.GetTempName
  tempName = tempPath & tempName
  If Len(suffix) > 0 Then
    If Right$(suffix, 1) = "." Then suffix = Left$(suffix, Len(suffix) - 1)
    If Left$(suffix, 1) <> "." Then suffix = "." & suffix
    tempName = tempName & suffix
  End If
  CreateTempFile = tempName
  Exit Function
EH:
  CreateTempFile = ""
End Function

Private Sub DeleteFileSafe(ByVal filePath As String)
  On Error Resume Next
  If Len(filePath) > 0 Then
    If FileExists(filePath) Then Kill filePath
  End If
  On Error GoTo 0
End Sub

Private Sub ClearFolderContents(ByVal folderPath As String)
  On Error GoTo EH
  Dim fso As Object
  Set fso = CreateObject("Scripting.FileSystemObject")
  If Not fso.FolderExists(folderPath) Then Exit Sub
  Dim folder As Object
  Set folder = fso.GetFolder(folderPath)
  Dim fileItem As Object
  For Each fileItem In folder.Files
    fileItem.Delete True
  Next fileItem
  Dim subFolder As Object
  Dim subPaths As Collection
  Set subPaths = New Collection
  For Each subFolder In folder.SubFolders
    subPaths.Add subFolder.path
  Next subFolder
  Dim onePath As Variant
  For Each onePath In subPaths
    fso.DeleteFolder CStr(onePath), True
  Next onePath
  Exit Sub
EH:
  ' ignore cleanup errors
End Sub

Private Function IsEdgeDriverCompatible(ByVal driverFile As String, ByVal edgeVersion As String) As Boolean
  If Len(driverFile) = 0 Then Exit Function
  If Not FileExists(driverFile) Then Exit Function

  Dim edgeMajor As String
  edgeMajor = ExtractMajorVersion(edgeVersion)
  If Len(edgeMajor) = 0 Then
    IsEdgeDriverCompatible = True
    Exit Function
  End If

  Dim driverVersion As String
  driverVersion = GetExecutableVersion(driverFile)
  Dim driverMajor As String
  driverMajor = ExtractMajorVersion(driverVersion)

  If Len(driverMajor) = 0 Then
    IsEdgeDriverCompatible = True
  Else
    IsEdgeDriverCompatible = (edgeMajor = driverMajor)
  End If
End Function

Private Function GetExecutableVersion(ByVal filePath As String) As String
  On Error GoTo EH
  Dim fso As Object
  Set fso = CreateObject("Scripting.FileSystemObject")
  GetExecutableVersion = Trim$(CStr(fso.GetFileVersion(filePath)))
  Exit Function
EH:
  GetExecutableVersion = ""
End Function

Private Function ExtractMajorVersion(ByVal version As String) As String
  Dim normalized As String
  normalized = Trim$(version)
  If Len(normalized) = 0 Then Exit Function
  Dim parts() As String
  parts = Split(normalized, ".")
  If UBound(parts) >= 0 Then ExtractMajorVersion = Trim$(parts(0))
End Function

Private Sub RegisterDriverForSeleniumBasic(ByVal driverFile As String)
  If Len(driverFile) = 0 Then Exit Sub
  If Not FileExists(driverFile) Then Exit Sub

  Dim targets As Collection
  Set targets = New Collection
  targets.Add CombinePath(Environ$("LOCALAPPDATA"), "SeleniumBasic")
  targets.Add CombinePath(Environ$("APPDATA"), "SeleniumBasic")
  targets.Add CombinePath(Environ$("PROGRAMFILES"), "SeleniumBasic")
  targets.Add CombinePath(Environ$("PROGRAMFILES(X86)"), "SeleniumBasic")
  targets.Add "C:\SeleniumBasic"

  Dim fso As Object
  Set fso = CreateObject("Scripting.FileSystemObject")
  Dim basePath As Variant
  For Each basePath In targets
    Dim base As String
    base = Trim$(CStr(basePath))
    If Len(base) = 0 Then GoTo NextBase
    If Not fso.FolderExists(base) Then GoTo NextBase
    CopyDriverIfNeeded fso, driverFile, base
    CopyDriverIfNeeded fso, driverFile, CombinePath(base, "drivers")
NextBase:
  Next basePath
End Sub

Private Sub CopyDriverIfNeeded(ByVal fso As Object, ByVal srcFile As String, ByVal destFolder As String)
  On Error Resume Next
  If Len(destFolder) = 0 Then Exit Sub
  If Not fso.FolderExists(destFolder) Then fso.CreateFolder destFolder
  If Not fso.FolderExists(destFolder) Then Exit Sub
  Dim destFile As String
  destFile = CombinePath(destFolder, fso.GetFileName(srcFile))
  fso.CopyFile srcFile, destFile, True
  On Error GoTo 0
End Sub

Private Function IsSeleniumBasicInstalled() As Boolean
  Dim targets As Collection
  Set targets = New Collection
  targets.Add CombinePath(Environ$("LOCALAPPDATA"), "SeleniumBasic")
  targets.Add CombinePath(Environ$("APPDATA"), "SeleniumBasic")
  targets.Add CombinePath(Environ$("PROGRAMFILES"), "SeleniumBasic")
  targets.Add CombinePath(Environ$("PROGRAMFILES(X86)"), "SeleniumBasic")
  targets.Add "C:\SeleniumBasic"

  Dim fso As Object
  Set fso = CreateObject("Scripting.FileSystemObject")
  Dim base As Variant
  For Each base In targets
    Dim path As String
    path = Trim$(CStr(base))
    If Len(path) = 0 Then GoTo NextBase
    If fso.FolderExists(path) Then
      If fso.FileExists(CombinePath(path, "SeleniumBasic.chm")) _
         Or fso.FileExists(CombinePath(path, "Selenium.dll")) Then
        IsSeleniumBasicInstalled = True
        Exit Function
      End If
    End If
NextBase:
  Next base
End Function

Private Sub ShowSeleniumBasicInstallGuide()
  Dim msg As String
  msg = "SeleniumBasic がインストールされていないため、Copilot ブラウザを起動できませんでした。" & vbCrLf & vbCrLf & _
        "SeleniumBasic のインストール手順を下記に出力しましたので、シート内の案内をご確認ください。"
  MsgBox msg, vbExclamation, "SeleniumBasic のインストールが必要です"
  OutputSeleniumBasicGuideToSheet
  SetStatus "SeleniumBasic のインストール手順をシートに出力しました。"
End Sub

Private Sub OutputSeleniumBasicGuideToSheet()
  On Error GoTo EH
  Dim ws As Worksheet
  Set ws = GetOrCreatePanel(HELPER_SHEET)

  ws.Range("B18:F25").Clear

  Dim area As Range
  Set area = ws.Range("B18:F24")
  area.HorizontalAlignment = xlLeft
  area.VerticalAlignment = xlTop
  area.WrapText = True

  With ws.Range("B18:F18")
    .Merge
    .value = "SeleniumBasicのインストール"
    .Font.Bold = True
  End With

  With ws.Range("B19:F19")
    .Merge
    .value = "1.リリースサイトにて実行ファイル(.exe)をクリックしてダウンロード"
  End With

  Dim linkCell As Range
  Set linkCell = ws.Range("B20")
  linkCell.value = "https://github.com/florentbr/SeleniumBasic/releases/tag/v2.0.9.0"
  linkCell.Hyperlinks.Add anchor:=linkCell, Address:=linkCell.value, TextToDisplay:=linkCell.value
  ws.Range("B20:F20").Merge

  With ws.Range("B21:F21")
    .Merge
    .value = "2.「WebDriver for Microsoft Edge」を選択してインストール"
  End With

  With ws.Range("B22:F22")
    .Merge
    .value = "   インストール先(デフォルト)： C:\Users\<ログインユーザー名>\AppData\Local\SeleniumBasic"
    .Font.Italic = True
  End With

  ws.Columns("B:F").ColumnWidth = 32
  Exit Sub
EH:
  ' シート更新に失敗した場合は黙って続行
End Sub

Private Function EdgeArchitectureTag() As String
  If InStr(1, DetectOSArchitecture(), "64", vbTextCompare) > 0 Then
    EdgeArchitectureTag = "win64"
  Else
    EdgeArchitectureTag = "win32"
  End If
End Function

Private Function EdgeDriverDownloadUrls(ByVal version As String, ByVal archTag As String) As Collection
  Dim list As Collection
  Set list = New Collection
  Dim baseVersion As String
  baseVersion = NormalizeEdgeVersion(version)
  If Len(baseVersion) = 0 Then Exit Function

  On Error Resume Next
  list.Add "https://msedgedriver.microsoft.com/" & baseVersion & "/edgedriver_" & archTag & ".zip"
  list.Add "https://msedgedriver.azureedge.net/" & baseVersion & "/edgedriver_" & archTag & ".zip"
  list.Add "https://msedgedriver.microsoft.com/api/zip?platform=" & archTag & "&version=" & baseVersion
  On Error GoTo 0

  Set EdgeDriverDownloadUrls = list
End Function

Private Function ResolveEdgeDriverVersion(ByVal installedVersion As String, ByVal archTag As String) As String
  Dim normalized As String
  normalized = NormalizeEdgeVersion(installedVersion)
  If Len(normalized) > 0 Then
    Dim directUrls As Collection
    Set directUrls = EdgeDriverPreferredPackageUrls(normalized, archTag)
    Dim directUrl As Variant
    For Each directUrl In directUrls
      If HttpResourceExists(CStr(directUrl)) Then
        ResolveEdgeDriverVersion = normalized
        Exit Function
      End If
    Next directUrl
  End If
  ResolveEdgeDriverVersion = GetLatestEdgeDriverVersion(installedVersion)
End Function

Private Function EdgeDriverPreferredPackageUrls(ByVal version As String, ByVal archTag As String) As Collection
  Dim list As Collection
  Set list = New Collection
  Dim baseVersion As String
  baseVersion = NormalizeEdgeVersion(version)
  If Len(baseVersion) = 0 Then Exit Function
  On Error Resume Next
  list.Add "https://msedgedriver.microsoft.com/" & baseVersion & "/edgedriver_" & archTag & ".zip"
  list.Add "https://msedgedriver.azureedge.net/" & baseVersion & "/edgedriver_" & archTag & ".zip"
  On Error GoTo 0
  Set EdgeDriverPreferredPackageUrls = list
End Function

Private Function GetInstalledEdgeVersion() As String
  Dim version As String
  version = ReadRegistryValue("HKEY_CURRENT_USER\Software\Microsoft\Edge\BLBeacon\version")
  If Len(version) = 0 Then version = ReadRegistryValue("HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Edge\BLBeacon\version")
  GetInstalledEdgeVersion = NormalizeEdgeVersion(version)
End Function

Private Function GetLatestEdgeDriverVersion(ByVal installedVersion As String) As String
  Dim version As String
  version = ""
  Dim major As String
  major = ""
  If Len(installedVersion) > 0 Then
    Dim parts() As String
    parts = Split(installedVersion, ".")
    If UBound(parts) >= 0 Then major = parts(0)
  End If

  If Len(major) > 0 Then
    version = DownloadTextFile("https://msedgedriver.microsoft.com/LATEST_RELEASE_" & major)
  End If
  If Len(version) = 0 Then
    version = DownloadTextFile("https://msedgedriver.microsoft.com/LATEST_RELEASE")
  End If
  If Len(version) = 0 Then
    version = DownloadTextFile("https://msedgedriver.microsoft.com/LATEST_STABLE")
  End If
  version = NormalizeEdgeVersion(version)
  If Len(version) = 0 Then version = NormalizeEdgeVersion(installedVersion)
  GetLatestEdgeDriverVersion = version
End Function

Private Function NormalizeEdgeVersion(ByVal value As String) As String
  Dim cleaned As String
  cleaned = NormalizeHttpText(value)
  Dim i As Long
  Dim ch As String
  Dim result As String
  For i = 1 To Len(cleaned)
    ch = Mid$(cleaned, i, 1)
    If (ch >= "0" And ch <= "9") Or ch = "." Or ch = "-" Then
      result = result & ch
    End If
  Next i
  NormalizeEdgeVersion = Trim$(result)
End Function

Private Function GetInstalledChromeVersion() As String
  Dim version As String
  version = ReadRegistryValue("HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon\version")
  If Len(version) = 0 Then version = ReadRegistryValue("HKEY_LOCAL_MACHINE\SOFTWARE\Google\Chrome\BLBeacon\version")
  GetInstalledChromeVersion = version
End Function

Private Function GetLatestChromeDriverVersion(ByVal installedVersion As String) As String
  Dim version As String
  version = ""
  Dim major As String
  major = ""
  If Len(installedVersion) > 0 Then
    Dim parts() As String
    parts = Split(installedVersion, ".")
    If UBound(parts) >= 0 Then major = parts(0)
  End If

  If Len(major) > 0 Then
    version = DownloadTextFile("https://chromedriver.storage.googleapis.com/LATEST_RELEASE_" & major)
  End If
  If Len(version) = 0 Then
    version = DownloadTextFile("https://chromedriver.storage.googleapis.com/LATEST_RELEASE")
  End If
  If Len(version) = 0 Then version = installedVersion
  GetLatestChromeDriverVersion = Trim$(version)
End Function

Private Function ReadRegistryValue(ByVal path As String) As String
  On Error GoTo EH
  Dim shell As Object
  Set shell = CreateObject("WScript.Shell")
  ReadRegistryValue = Trim$(shell.RegRead(path) & "")
  Exit Function
EH:
  ReadRegistryValue = ""
End Function

'========================
'      低レベル関数
'========================
Private Function CleanPath(ByVal pathIn As String) As String
  Dim p As String
  p = Trim$(CStr(pathIn))
  If Len(p) = 0 Then Exit Function
  If Len(p) >= 2 Then
    If Left$(p, 1) = Chr$(34) And Right$(p, 1) = Chr$(34) Then p = Mid$(p, 2, Len(p) - 2)
  End If
  If LCase$(Left$(p, 8)) = "file:///" Then
    p = Mid$(p, 9)
  ElseIf LCase$(Left$(p, 7)) = "file://" Then
    p = Mid$(p, 8)
  End If
  p = Replace(p, "/", Application.PathSeparator)
  p = Trim$(p)
  If InStr(1, p, ":", vbBinaryCompare) = 0 And Left$(p, 2) <> "\\" Then
    Dim base As String: base = ThisWorkbook.path
    If Len(base) > 0 Then
      If Right$(base, 1) = Application.PathSeparator Then p = base & p Else p = base & Application.PathSeparator & p
    End If
  End If
  CleanPath = p
End Function

Private Sub ReopenDictionaryWorkbook(ByVal csvPath As String)
  Dim cleaned As String: cleaned = CleanPath(csvPath)
  If Len(cleaned) = 0 Then Exit Sub
  Dim oldAlerts As Boolean
  oldAlerts = Application.DisplayAlerts
  Application.DisplayAlerts = False
  On Error Resume Next
  Application.Workbooks.Open fileName:=cleaned, UpdateLinks:=False, ReadOnly:=False
  Application.DisplayAlerts = oldAlerts
  On Error GoTo 0
End Sub

Private Function EnsureDictionaryWorkbookWritable(ByVal csvPath As String, ByRef reopenAfter As Boolean) As Boolean
  Dim cleaned As String: cleaned = CleanPath(csvPath)
  If Len(cleaned) = 0 Then Exit Function

  Dim target As Workbook
  Dim wb As Workbook
  For Each wb In Application.Workbooks
    On Error Resume Next
    If LCase$(CleanPath(wb.fullName)) = LCase$(cleaned) Then
      Set target = wb
      Exit For
    End If
  Next wb
  On Error GoTo 0

  Dim probe As Workbook
  Dim oldAlerts As Boolean
  oldAlerts = Application.DisplayAlerts
  Application.DisplayAlerts = False

  On Error GoTo EH

  If Not target Is Nothing Then
    reopenAfter = True
    If target.Saved = False Then target.Save
    target.Close SaveChanges:=False
  Else
    reopenAfter = False
  End If

  Set probe = Application.Workbooks.Open(fileName:=cleaned, UpdateLinks:=False, ReadOnly:=False)
  If probe Is Nothing Then Err.Raise vbObjectError + 200, , "Open failed"
  If probe.ReadOnly Then Err.Raise vbObjectError + 201, , "File locked"
  probe.Close SaveChanges:=False
  Set probe = Nothing

  EnsureDictionaryWorkbookWritable = True
  GoTo CleanExit

EH:
  EnsureDictionaryWorkbookWritable = False
  reopenAfter = False
  On Error Resume Next
  If Not probe Is Nothing Then probe.Close SaveChanges:=False
  Application.DisplayAlerts = oldAlerts
  On Error GoTo 0
  MsgBox "辞書CSVが他のユーザーによって使用中です。閉じてから再実行してください。" & vbCrLf & "対象: " & cleaned, vbExclamation
  SetStatus "辞書CSVが他のユーザーによってロックされています: " & cleaned
  Exit Function

CleanExit:
  On Error Resume Next
  Application.DisplayAlerts = oldAlerts
  On Error GoTo 0
End Function

Private Function GetTargetWorkbook(ByVal pathIn As String) As Workbook
  Dim path As String: path = CleanPath(pathIn)
  Dim wb As Workbook
  If Len(path) = 0 Or LCase$(path) = LCase$(ThisWorkbook.fullName) Then
    Set GetTargetWorkbook = ThisWorkbook: Exit Function
  End If
  For Each wb In Application.Workbooks
    If LCase$(wb.fullName) = LCase$(path) Then Set GetTargetWorkbook = wb: Exit Function
  Next
  On Error Resume Next
  Set wb = Application.Workbooks.Open(fileName:=path, ReadOnly:=False)
  On Error GoTo 0
  Set GetTargetWorkbook = wb
End Function

Private Function GetTextCellsRange(ws As Worksheet) As Range
  Dim baseRng As Range, visRng As Range, extra As Range, targetRng As Range, textRng As Range
  Dim startRow As Long: startRow = RANGE_START_ROW
  Dim startCol As Long: startCol = RANGE_START_COL
  Dim endRow As Long: endRow = startRow + TRANSLATION_MAX_ROWS - 1
  Dim endCol As Long: endCol = startCol + TRANSLATION_MAX_COLS - 1
  If endRow > ws.Rows.Count Then endRow = ws.Rows.Count
  If endCol > ws.Columns.Count Then endCol = ws.Columns.Count
  Set baseRng = ws.Range(ws.Cells(startRow, startCol), ws.Cells(endRow, endCol))
  On Error Resume Next
  Set visRng = baseRng.SpecialCells(xlCellTypeVisible)
  If visRng Is Nothing Then Set visRng = baseRng

  Dim cell As Range
  For Each cell In visRng
    If cell.MergeCells Then
      If extra Is Nothing Then
        Set extra = cell.MergeArea.Cells(1, 1)
      Else
        Set extra = Union(extra, cell.MergeArea.Cells(1, 1))
      End If
    End If
  Next cell

  If extra Is Nothing Then
    Set targetRng = visRng
  Else
    Set targetRng = Union(visRng, extra)
  End If

  Set textRng = targetRng.SpecialCells(xlCellTypeConstants, xlTextValues)
  On Error GoTo 0
  If textRng Is Nothing Then Set textRng = targetRng
  Set GetTextCellsRange = textRng
End Function

Private Function SheetProtected(ws As Worksheet) As Boolean
  On Error Resume Next
  SheetProtected = ws.ProtectContents
  On Error GoTo 0
End Function

Private Function IsInternalSheet(ByVal ws As Worksheet) As Boolean
  Dim nm As String
  nm = ws.Name
  If StrComp(nm, HELPER_SHEET, vbTextCompare) = 0 Then
    IsInternalSheet = True
  End If
End Function

' 適用（戻り値: 変更セル/図形数）
Private Function ApplyToSheet(ws As Worksheet, entries As Collection) As Long
  Dim textRng As Range: Set textRng = GetTextCellsRange(ws)
  On Error Resume Next
  If Not textRng Is Nothing Then textRng.Font.Name = "Arial"
  On Error GoTo 0
  Dim idx As Object: Set idx = BuildIndex(entries)
  Dim processedMerges As Object: Set processedMerges = CreateObject("Scripting.Dictionary")
  processedMerges.CompareMode = vbTextCompare
  Dim cell As Range, key As String, changed As Long, entry As Object
  Dim targetCell As Range, targetRange As Range, mergeKey As String
  Dim total As Long
  If textRng Is Nothing Then
    total = 0
  Else
    total = textRng.Cells.Count
  End If
  Dim i As Long: i = 0

  If Not textRng Is Nothing Then
    For Each cell In textRng.Cells
      i = i + 1
      If (i Mod 200) = 0 Then Application.StatusBar = "Applying " & ws.Name & "... (" & i & "/" & total & ")"
      Set targetRange = cell
      Set targetCell = cell
      If cell.MergeCells Then
        Set targetRange = cell.MergeArea
        Set targetCell = targetRange.Cells(1, 1)
        mergeKey = targetRange.Address(False, False)
        If processedMerges.Exists(mergeKey) Then GoTo NextCell
        processedMerges.Add mergeKey, True
      End If
      If VarType(targetCell.Value2) = vbString Then
        key = KeyFor(CStr(targetCell.Value2))
        If Len(key) > 0 And idx.Exists(key) Then
          Set entry = idx.item(key)
          If CStr(targetCell.Value2) <> CStr(entry.item("target")) Then
            targetRange.Value2 = entry.item("target")
            ApplyStyleIfAny targetRange, entry
            targetRange.Font.Name = "Arial"
            changed = changed + 1
          End If
        End If
      End If
NextCell:
    Next
  End If

' 図形の翻訳
  Dim rangeEndRow As Long: rangeEndRow = RANGE_START_ROW + TRANSLATION_MAX_ROWS - 1
  Dim rangeEndCol As Long: rangeEndCol = RANGE_START_COL + TRANSLATION_MAX_COLS - 1
  If rangeEndRow > ws.Rows.Count Then rangeEndRow = ws.Rows.Count
  If rangeEndCol > ws.Columns.Count Then rangeEndCol = ws.Columns.Count
  Dim targetRect As Range
  Set targetRect = ws.Range(ws.Cells(RANGE_START_ROW, RANGE_START_COL), ws.Cells(rangeEndRow, rangeEndCol))

  Dim shapesInScope As New Collection, shp As Shape
  CollectTextShapes ws.Shapes, targetRect, shapesInScope

  For Each shp In shapesInScope
    ForceShapeFontArial shp
    Dim sTxt As String: sTxt = GetShapeText(shp)
    If Len(sTxt) > 0 Then
      key = KeyFor(sTxt)
      If Len(key) > 0 And idx.Exists(key) Then
        Set entry = idx.item(key)
        Dim tgt As String: tgt = CStr(entry.item("target"))
        If sTxt <> tgt Then
          SetShapeText shp, tgt
          ApplyShapeStyleIfAny shp, entry
          ForceShapeFontArial shp
          changed = changed + 1
        End If
      End If
    End If
  Next

  Application.StatusBar = False
  ApplyToSheet = changed
End Function

Private Sub ApplyStyleIfAny(ByVal cell As Range, ByVal entry As Object)
  On Error Resume Next
  Dim fn As String: fn = entry.item("font_name") & ""
  If Len(fn) > 0 Then cell.Font.Name = fn

  Dim fs As Variant: fs = entry.item("font_size")
  If Not IsEmpty(fs) And Len(Trim$(fs & "")) > 0 Then
    If IsNumeric(fs) Then cell.Font.size = CDbl(fs)
  End If

  Dim b As Variant: b = entry.item("bold")
  If Not IsEmpty(b) And Len(Trim$(b & "")) > 0 Then
    cell.Font.Bold = (UCase$(CStr(b)) = "1" Or UCase$(CStr(b)) = "TRUE")
  End If

  Dim al As String: al = LCase$(Trim$(entry.item("align") & ""))
  Select Case al
    Case "left":   cell.HorizontalAlignment = xlHAlignLeft
    Case "center", "centre": cell.HorizontalAlignment = xlHAlignCenter
    Case "right":  cell.HorizontalAlignment = xlHAlignRight
  End Select
  On Error GoTo 0
End Sub

'========================
'   図形（テキストボックス等）ユーティリティ
'========================
Private Function ShapeInRange(ByVal shp As Shape, ByVal rng As Range) As Boolean
  On Error GoTo EH

  Dim eps As Double
  eps = SHAPE_BOUNDS_EPSILON

  Dim rngLeft As Double
  Dim rngTop As Double
  Dim rngRight As Double
  Dim rngBottom As Double

  rngLeft = rng.Left
  rngTop = rng.Top
  rngRight = rngLeft + rng.Width
  rngBottom = rngTop + rng.Height

  Dim shpLeft As Double
  Dim shpTop As Double
  Dim shpRight As Double
  Dim shpBottom As Double

  shpLeft = shp.Left
  shpTop = shp.Top
  shpRight = shpLeft + shp.Width
  shpBottom = shpTop + shp.Height

  If shpRight < rngLeft - eps Then GoTo Outside
  If shpLeft > rngRight + eps Then GoTo Outside
  If shpBottom < rngTop - eps Then GoTo Outside
  If shpTop > rngBottom + eps Then GoTo Outside

  ShapeInRange = True
  Exit Function

Outside:
  ShapeInRange = False
  Exit Function

EH:
  ShapeInRange = False
End Function

Private Sub CollectTextShapes(ByVal parentShapes As Object, ByVal targetRng As Range, ByRef out As Collection)
  Dim shp As Shape
  For Each shp In parentShapes
    If shp.Type = msoGroup Then
      CollectTextShapes shp.GroupItems, targetRng, out
    Else
      If shp.Visible = msoFalse Then GoTo NextShape
      If ShapeInRange(shp, targetRng) Then
        Dim hasTxt As Boolean
        On Error Resume Next
        hasTxt = (shp.TextFrame2.HasText)
        On Error GoTo 0
        If Not hasTxt Then
          On Error Resume Next
          hasTxt = (shp.TextFrame.HasText)
          On Error GoTo 0
        End If
        If hasTxt Then out.Add shp
      End If
    End If
NextShape:
    ' continue
  Next
End Sub

Private Function GetShapeText(ByVal shp As Shape) As String
  On Error Resume Next
  GetShapeText = shp.TextFrame2.TextRange.text
  If Len(GetShapeText) = 0 Then GetShapeText = shp.TextFrame.Characters.text
  On Error GoTo 0
End Function

Private Sub SetShapeText(ByVal shp As Shape, ByVal newText As String)
  On Error Resume Next
  shp.TextFrame2.TextRange.text = newText
  If GetShapeText(shp) <> newText Then shp.TextFrame.Characters.text = newText
  On Error GoTo 0
End Sub

Private Sub ApplyShapeStyleIfAny(ByVal shp As Shape, ByVal entry As Object)
  On Error Resume Next
  Dim fn As String: fn = entry.item("font_name") & ""
  If Len(fn) > 0 Then shp.TextFrame2.TextRange.Font.Name = fn

  Dim fs As Variant: fs = entry.item("font_size")
  If Not IsEmpty(fs) And Len(Trim$(fs & "")) > 0 Then
    If IsNumeric(fs) Then shp.TextFrame2.TextRange.Font.size = CDbl(fs)
  End If

  Dim b As Variant: b = entry.item("bold")
  If Not IsEmpty(b) And Len(Trim$(b & "")) > 0 Then
    shp.TextFrame2.TextRange.Font.Bold = IIf(UCase$(CStr(b)) = "1" Or UCase$(CStr(b)) = "TRUE", msoTrue, msoFalse)
  End If

  Dim al As String: al = LCase$(Trim$(entry.item("align") & ""))
  Select Case al
    Case "left":   shp.TextFrame2.TextRange.ParagraphFormat.Alignment = msoAlignLeft
    Case "center", "centre": shp.TextFrame2.TextRange.ParagraphFormat.Alignment = msoAlignCenter
    Case "right":  shp.TextFrame2.TextRange.ParagraphFormat.Alignment = msoAlignRight
  End Select
  On Error GoTo 0
End Sub

Private Sub ForceShapeFontArial(ByVal shp As Shape)
  On Error Resume Next
  shp.TextFrame2.TextRange.Font.Name = "Arial"
  shp.TextFrame.Characters.Font.Name = "Arial"
  On Error GoTo 0
End Sub

'========================
'   辞書読み込み（毎回CSV）
'========================
Private Function EnsureDictionaryLoaded(ByVal csvPath As String) As Collection
  Dim cleaned As String: cleaned = CleanPath(csvPath)
  If Len(cleaned) = 0 Or Dir$(cleaned) = "" Then
    SetStatus "Dictionary path invalid or not found: " & cleaned
    Set EnsureDictionaryLoaded = New Collection
    Exit Function
  End If

  Dim reopenAfter As Boolean
  reopenAfter = False
  If Not EnsureDictionaryWorkbookWritable(cleaned, reopenAfter) Then
    Set EnsureDictionaryLoaded = New Collection
    Exit Function
  End If

  Dim loaded As Collection
  Set loaded = LoadDictionaryFromCSV(cleaned)

  If reopenAfter Then ReopenDictionaryWorkbook cleaned

  If loaded Is Nothing Then
    Dim detail As String: detail = cleaned
    Dim errDetail As String: errDetail = LastCsvErrorDetail()
    If Len(errDetail) > 0 Then detail = detail & " [" & errDetail & "]"
    SetStatus "Dictionary load failed (empty or format error): " & detail
    Set EnsureDictionaryLoaded = New Collection
  Else
    Set EnsureDictionaryLoaded = loaded
  End If
End Function

Private Function LoadDictionaryFromCSV(ByVal csvPath As String) As Collection
  csvPath = CleanPath(csvPath)

  Dim parsed As Collection
  Set parsed = ParseCsvFile(csvPath) ' UTF-8直読

  If parsed Is Nothing Then
    Set LoadDictionaryFromCSV = Nothing
  Else
    Set LoadDictionaryFromCSV = parsed
  End If
End Function

'========================
'  CSV UTF-8 直読 + パース
'========================
Private Function ParseCsvFile(ByVal csvPath As String) As Collection
  On Error GoTo ErrH
  g_lastCsvError = ""
  g_lastCsvStage = "init"
  If Len(Dir$(csvPath)) = 0 Then
    g_lastCsvError = "file not found"
    g_lastCsvStage = "file check"
    Exit Function
  End If

  Dim fileSize As Long
  On Error Resume Next
  fileSize = FileLen(csvPath)
  On Error GoTo ErrH
  If fileSize = 0 Then
    g_lastCsvError = "file size is 0"
    Exit Function
  End If

  Dim text As String
  g_lastCsvStage = "read text utf-8"
  On Error Resume Next
  text = ReadAllTextUTF8(csvPath)
  If Err.Number <> 0 Then
    g_lastCsvError = "read text throw " & Err.Number & ": " & Err.description
    g_lastCsvStage = "read text utf-8 call"
    Err.Clear
    Exit Function
  End If
  On Error GoTo ErrH
  If Len(text) = 0 Then
    g_lastCsvError = "text read as empty"
    g_lastCsvStage = "read text"
    Exit Function
  End If
  g_lastCsvStage = "normalize newlines"
  text = Replace(Replace(text, vbCrLf, vbLf), vbCr, vbLf)

  Dim lines() As String
  Dim lineCount As Long
  ReDim lines(0 To 0)
  lineCount = 0

  Dim currentLine As String
  Dim inQuotes As Boolean
  Dim charIndex As Long
  Dim ch As String
  Dim advance As Long
  Dim textLen As Long: textLen = Len(text)

  charIndex = 1
  Do While charIndex <= textLen
    ch = Mid$(text, charIndex, 1)
    advance = 1
    If ch = """" Then
      If inQuotes Then
        If charIndex < textLen And Mid$(text, charIndex + 1, 1) = """" Then
          currentLine = currentLine & """" & """"
          advance = 2
        Else
          inQuotes = False
          currentLine = currentLine & ch
        End If
      Else
        inQuotes = True
        currentLine = currentLine & ch
      End If
    ElseIf ch = vbLf Then
      If inQuotes Then
        currentLine = currentLine & ch
      Else
        PushField lines, lineCount, currentLine
        currentLine = vbNullString
      End If
    Else
      currentLine = currentLine & ch
    End If
    charIndex = charIndex + advance
  Loop
  PushField lines, lineCount, currentLine

  Dim colSource As Long, colTarget As Long
  Dim colFontName As Long, colFontSize As Long, colAlign As Long, colBold As Long
  colSource = -1: colTarget = -1: colFontName = -1: colFontSize = -1: colAlign = -1: colBold = -1

  Dim out As New Collection
  Dim i As Long, fields As Variant, headerDone As Boolean

  ' ヘッダ解析
  g_lastCsvStage = "header scan"
  For i = LBound(lines) To UBound(lines)
    If Len(Trim$(lines(i))) = 0 Then GoTo NextLine
    g_lastCsvStage = "header line " & CStr(i)
    fields = CsvFields(lines(i))
    If i = LBound(lines) Then
      If VBA.Len(fields(0)) > 0 Then
        If AscW(Left$(fields(0), 1)) = &HFEFF Then fields(0) = Mid$(fields(0), 2)
      End If
    End If
    Dim j As Long, h As String
    For j = LBound(fields) To UBound(fields)
      h = LCase$(Trim$(CStr(fields(j))))
      If h = "source" Then colSource = j
      If h = "target" Then colTarget = j
      If h = "font_name" Then colFontName = j
      If h = "font_size" Then colFontSize = j
      If h = "align" Then colAlign = j
      If h = "bold" Then colBold = j
    Next j
    If colSource >= 0 And colTarget >= 0 Then headerDone = True
    Exit For
NextLine:
  Next i

  Dim startRow As Long
  If headerDone Then
    startRow = i + 1
  Else
    colSource = 0: colTarget = 1
    startRow = LBound(lines)
  End If

  g_lastCsvStage = "data rows"
  For i = startRow To UBound(lines)
    g_lastCsvStage = "data line " & CStr(i)
    If Len(Trim$(lines(i))) = 0 Then GoTo NextData
    fields = CsvFields(lines(i))
    If UBound(fields) < colTarget Then GoTo NextData
    Dim src As String: src = Trim$(CStr(fields(colSource)))
    If Len(src) = 0 Then GoTo NextData
    Dim e As Object: Set e = CreateObject("Scripting.Dictionary")
    e.Add "source", src
    e.Add "target", FieldOrEmpty(fields, colTarget)
    e.Add "font_name", FieldOrEmpty(fields, colFontName)
    e.Add "font_size", FieldOrEmpty(fields, colFontSize)
    e.Add "align", FieldOrEmpty(fields, colAlign)
    e.Add "bold", FieldOrEmpty(fields, colBold)
    out.Add e
NextData:
  Next i

  Set ParseCsvFile = out
  If out.Count = 0 Then
    If Len(g_lastCsvError) = 0 Then g_lastCsvError = "parsed entry count = 0"
    g_lastCsvStage = "final count"
  Else
    g_lastCsvError = ""
    g_lastCsvStage = ""
  End If
  Exit Function
ErrH:
  Dim stageInfo As String
  If Len(g_lastCsvStage) > 0 Then
    stageInfo = "stage=" & g_lastCsvStage & "; "
  Else
    stageInfo = ""
  End If
  g_lastCsvError = stageInfo & "parse error " & Err.Number & ": " & Err.description
  Set ParseCsvFile = Nothing
End Function

Private Function LastCsvErrorDetail() As String
  Dim detail As String
  If Len(g_lastCsvError) > 0 Then detail = g_lastCsvError
  If Len(g_lastCsvStage) > 0 Then
    If Len(detail) > 0 Then
      detail = detail & "; stage=" & g_lastCsvStage
    Else
      detail = "stage=" & g_lastCsvStage
    End If
  End If
  LastCsvErrorDetail = detail
End Function

Private Function FieldOrEmpty(ByVal fields As Variant, ByVal idx As Long) As String
  If idx >= 0 And idx <= UBound(fields) Then FieldOrEmpty = CStr(fields(idx)) Else FieldOrEmpty = ""
End Function

' --- CSVテキスト読み込み（MultiByteToWideChar ベース） ---
Private Function ReadAllTextUTF8(ByVal path As String) As String
  Dim text As String

  text = ReadAllTextWithCodePage(path, CP_UTF8)
  If Len(text) > 0 Then
    ReadAllTextUTF8 = text
    Exit Function
  End If

  text = ReadAllTextWithCodePage(path, CP_SHIFT_JIS)
  If Len(text) > 0 Then
    ReadAllTextUTF8 = text
    Exit Function
  End If

  text = ReadAllTextWithCodePage(path, CP_ACP)
  If Len(text) > 0 Then
    ReadAllTextUTF8 = text
  Else
    ReadAllTextUTF8 = ""
  End If
End Function

Private Function ReadAllTextWithCodePage(ByVal path As String, ByVal codePage As Long) As String
  On Error GoTo EH
  If Len(path) = 0 Or Dir$(path) = "" Then Exit Function

  Dim data() As Byte
  If Not ReadAllBytes(path, data) Then Exit Function

  Dim startIdx As Long
  Dim byteCount As Long
  startIdx = LBound(data)
  byteCount = UBound(data) - startIdx + 1
  If byteCount <= 0 Then Exit Function

  If codePage = CP_UTF8 Then
    If byteCount >= 3 Then
      If data(startIdx) = &HEF And data(startIdx + 1) = &HBB And data(startIdx + 2) = &HBF Then
        startIdx = startIdx + 3
        byteCount = byteCount - 3
        If byteCount <= 0 Then Exit Function
      End If
    End If
  End If

  ReadAllTextWithCodePage = BytesToWideString(data, startIdx, byteCount, codePage)
  Exit Function
EH:
  ReadAllTextWithCodePage = ""
End Function

Private Function ReadAllBytes(ByVal path As String, ByRef data() As Byte) As Boolean
  Dim f As Integer: f = 0
  On Error GoTo EH
  If Len(path) = 0 Or Dir$(path) = "" Then Exit Function

  f = FreeFile
  Open path For Binary Access Read Shared As #f
  Dim size As Long: size = LOF(f)
  If size <= 0 Then
    Close #f
    f = 0
    Exit Function
  End If

  ReDim data(0 To size - 1) As Byte
  Get #f, 1, data

  Close #f
  f = 0
  ReadAllBytes = True
  Exit Function
EH:
  ReadAllBytes = False
  On Error Resume Next
  If f <> 0 Then Close #f
  On Error GoTo 0
End Function

Private Function BytesToWideString(ByRef data() As Byte, ByVal startIndex As Long, ByVal byteCount As Long, ByVal codePage As Long) As String
  If byteCount <= 0 Then Exit Function

#If VBA7 Then
  Dim ptrBytes As LongPtr
  ptrBytes = VarPtr(data(startIndex))
  Dim ptrWide As LongPtr
#Else
  Dim ptrBytes As Long
  ptrBytes = VarPtr(data(startIndex))
  Dim ptrWide As Long
#End If

  Dim charCount As Long
  charCount = MultiByteToWideChar(codePage, 0, ptrBytes, byteCount, 0, 0)
  If charCount <= 0 Then Exit Function

  Dim buffer As String
  buffer = String$(charCount, vbNullChar)
#If VBA7 Then
  ptrWide = StrPtr(buffer)
#Else
  ptrWide = StrPtr(buffer)
#End If

  charCount = MultiByteToWideChar(codePage, 0, ptrBytes, byteCount, ptrWide, charCount)
  If charCount <= 0 Then Exit Function

  BytesToWideString = Left$(buffer, charCount)
End Function


' --- CSV 1行を安全分割（PushField で配列末尾追加） ---
Private Sub PushField(ByRef arr() As String, ByRef n As Long, ByVal value As String)
  ReDim Preserve arr(0 To n)
  arr(n) = value
  n = n + 1
End Sub

Private Function CsvFields(ByVal line As String) As Variant
  Dim arr() As String: ReDim arr(0 To 0)
  Dim n As Long: n = 0

  Dim field As String
  Dim inQuotes As Boolean
  Dim i As Long, ch As String

  For i = 1 To Len(line)
    ch = Mid$(line, i, 1)
    If ch = """" Then
      If inQuotes And i < Len(line) And Mid$(line, i + 1, 1) = """" Then
        field = field & """"      ' 連続二重引用符はエスケープ
        i = i + 1
      Else
        inQuotes = Not inQuotes   ' クオートの開閉
      End If
    ElseIf ch = "," And Not inQuotes Then
      PushField arr, n, field     ' フィールド確定
      field = vbNullString
    Else
      field = field & ch
    End If
  Next
  PushField arr, n, field         ' 行末の最後のフィールド

  CsvFields = arr
End Function

' 後勝ち・安全：Exists→Remove→Add
Private Function BuildIndex(entries As Collection) As Object
  Dim idx As Object: Set idx = CreateObject("Scripting.Dictionary")
  idx.CompareMode = 1
  Dim entry As Variant, k As String
  For Each entry In entries
    k = KeyFor(CStr(entry.item("source")))
    If Len(k) > 0 Then
      If idx.Exists(k) Then idx.Remove k
      idx.Add k, entry
    End If
  Next
  Set BuildIndex = idx
End Function

'========================
'   正規化
'========================
Private Function NormalizeKeyText(ByVal s As String) As String
  Dim t As String: t = CStr(s)
  t = Replace(t, vbCr, " ")
  t = Replace(t, vbLf, " ")
  t = Replace(t, vbTab, " ")
  t = Replace(t, Chr(160), " ")
  t = Replace(t, ChrW(&H3000), " ")
  t = Replace(t, ChrW(&H202F), " ")
  t = Replace(t, "（", "(")
  t = Replace(t, "）", ")")
  t = Replace(t, ChrW(&H2212), "-")
  t = Replace(t, ChrW(&H2013), "-")
  t = Replace(t, ChrW(&H2014), "-")
  Do While InStr(1, t, "  ") > 0: t = Replace(t, "  ", " "): Loop
  t = Trim$(t)
  If NORMALIZE_WIDE_NARROW Then On Error Resume Next: t = StrConv(t, vbNarrow): On Error GoTo 0
  If IGNORE_ALL_SPACES_WHEN_MATCHING Then t = Replace(t, " ", "")
  NormalizeKeyText = t
End Function

Private Function KeyFor(ByVal s As String) As String
  KeyFor = LCase$(NormalizeKeyText(s))
End Function

Private Function SafeText(v As Variant) As String
  If IsError(v) Then SafeText = "" Else SafeText = CStr(v)
End Function

Private Function BackupPath(ByVal fullName As String) As String
  Dim p As String, n As String, ext As String
  p = Left$(fullName, InStrRev(fullName, Application.PathSeparator))
  n = Mid$(fullName, InStrRev(fullName, Application.PathSeparator) + 1)
  Dim dotPos As Long: dotPos = InStrRev(n, ".")
  If dotPos > 0 Then
    ext = Mid$(n, dotPos)
    n = Left$(n, dotPos - 1)
  Else
    ext = ""
  End If
  BackupPath = p & n & "_backup_" & Format(Now, "yyyymmdd_hhnnss") & ext
End Function

Private Sub SetStatus(ByVal msg As String)
  On Error GoTo EH
  Dim ws As Worksheet
  Set ws = ThisWorkbook.Worksheets(HELPER_SHEET)
  Dim target As Range
  Set target = ws.Range(CELL_STATUS)

  With target
    .value = msg
    .WrapText = True
    .HorizontalAlignment = xlLeft
    .VerticalAlignment = xlTop
  End With

  AdjustMergedRowHeight target, 36, 160
  Exit Sub
EH:
  ' ステータス更新に失敗しても処理継続
End Sub

Private Function AppendError(ByVal baseMsg As String, ByVal newMsg As String) As String
  Dim trimmedNew As String
  trimmedNew = Trim$(newMsg)
  If Len(trimmedNew) = 0 Then
    AppendError = Trim$(baseMsg)
  ElseIf Len(Trim$(baseMsg)) = 0 Then
    AppendError = trimmedNew
  Else
    AppendError = Trim$(baseMsg) & vbCrLf & trimmedNew
  End If
End Function

Private Function AppendLine(ByVal baseText As String, ByVal newLine As String) As String
  Dim trimmed As String
  trimmed = CStr(newLine)
  If Len(baseText) = 0 Then
    AppendLine = trimmed
  Else
    AppendLine = baseText & vbCrLf & trimmed
  End If
End Function

Private Sub CopyDiagnosticsToClipboard(ByVal textValue As String)
  Dim succeeded As Boolean
  On Error Resume Next
  Dim dataObj As Object
  Set dataObj = CreateObject("MSForms.DataObject")
  If Not dataObj Is Nothing Then
    dataObj.SetText CStr(textValue)
    dataObj.PutInClipboard
    succeeded = (Err.Number = 0)
  End If
  On Error GoTo 0
  If succeeded Then Exit Sub

  If ClipboardPutText(textValue) Then Exit Sub

  MsgBox "診断レポートのクリップボードコピーに失敗しました。手動で選択しコピーしてください。", vbExclamation, "クリップボードエラー"
End Sub

Private Function ClipboardPutText(ByVal textValue As String) As Boolean
  On Error GoTo EH
  Dim unicodeText As String
  unicodeText = CStr(textValue)
  Dim textWithNull As String
  textWithNull = unicodeText & vbNullChar

  Dim byteLen As LongPtr
  byteLen = Len(textWithNull) * 2
  Dim hMem As LongPtr
  hMem = GlobalAlloc(GMEM_MOVEABLE Or GMEM_ZEROINIT, byteLen)
  If hMem = 0 Then Exit Function
  Dim ptr As LongPtr
  ptr = GlobalLock(hMem)
  If ptr = 0 Then
    GlobalFree hMem
    Exit Function
  End If
  CopyMemory ptr, StrPtr(textWithNull), byteLen
  GlobalUnlock hMem

  If OpenClipboard(0) = 0 Then
    GlobalFree hMem
    Exit Function
  End If
  EmptyClipboard
  If SetClipboardData(CF_UNICODETEXT, hMem) = 0 Then
    CloseClipboard
    GlobalFree hMem
    Exit Function
  End If
  CloseClipboard
  ClipboardPutText = True
  Exit Function
EH:
  ClipboardPutText = False
End Function

Private Sub AdjustMergedRowHeight(ByVal targetRange As Range, ByVal minHeight As Double, ByVal maxHeight As Double)
  On Error GoTo EH
  If targetRange Is Nothing Then Exit Sub

  Dim ws As Worksheet
  Set ws = targetRange.Worksheet

  Dim area As Range
  Set area = targetRange.MergeArea
  Dim rowIndex As Long
  rowIndex = area.Row
  Dim wasMerged As Boolean
  wasMerged = area.MergeCells

  Dim storedValue As Variant
  storedValue = area.Cells(1, 1).value

  If wasMerged Then
    area.MergeCells = False
  End If

  area.WrapText = True
  area.Rows.AutoFit

  Dim newHeight As Double
  newHeight = area.Rows(1).RowHeight
  If newHeight < minHeight Then newHeight = minHeight
  If newHeight > maxHeight Then newHeight = maxHeight
  ws.Rows(rowIndex).RowHeight = newHeight

Cleanup:
  If wasMerged Then
    On Error Resume Next
    If Not area.MergeCells Then area.Merge
    area.Cells(1, 1).value = storedValue
    area.WrapText = True
    area.HorizontalAlignment = xlLeft
    area.VerticalAlignment = xlTop
    On Error GoTo 0
  End If
  Exit Sub
EH:
  Resume Cleanup
End Sub

'========================
'    絵文字ヘルパ
'========================
Private Function UiIcon(ByVal Name As String) As String
  Select Case LCase(Name)
    Case "folder":   UiIcon = ChrW(&HD83D) & ChrW(&HDDC2)
    Case "search":   UiIcon = ChrW(&HD83D) & ChrW(&HDD0E)
    Case "index":    UiIcon = ChrW(&HD83D) & ChrW(&HDDC2)
    Case "compass":  UiIcon = ChrW(&HD83E) & ChrW(&HDDED)
    Case "flask":    UiIcon = ChrW(&HD83E) & ChrW(&HDDEA)
    Case "check":    UiIcon = ChrW(&H2705)
    Case "play":     UiIcon = ChrW(&H25B6)
    Case "allok":    UiIcon = ChrW(&H2714)
    Case "allng":    UiIcon = ChrW(&H2716)
    Case "info":     UiIcon = ChrW(&H2139)
    Case "broom":    UiIcon = ChrW(&HD83E) & ChrW(&HDDF9)
    Case "globe":    UiIcon = ChrW(&HD83C) & ChrW(&HDF10)
    Case "robot":    UiIcon = ChrW(&HD83E) & ChrW(&HDD16)
    Case Else:       UiIcon = ""
  End Select
End Function

Private Function LabelWithIcon(iconName As String, text As String) As String
  If USE_EMOJI Then
    LabelWithIcon = UiIcon(iconName) & " " & text
  Else
    LabelWithIcon = text
  End If
End Function

'========================
'   互換（未使用）FNV-1a
'========================
Private Function FileSignature(ByVal path As String, ByRef mtime As Date, ByRef fsize As Double, ByRef hashOut As String) As Boolean
  On Error GoTo EH
  If Len(path) = 0 Or Dir$(path) = "" Then
    FileSignature = False
    mtime = 0: fsize = 0: hashOut = ""
    Exit Function
  End If
  mtime = FileDateTime(path)
  fsize = FileLen(path)
  Dim txt As String: txt = ReadAllTextUTF8(path)
  hashOut = Fnv1a32Hex(txt)
  FileSignature = True
  Exit Function
EH:
  FileSignature = False
  mtime = 0: fsize = 0: hashOut = ""
End Function

Private Function Fnv1a32Hex(ByVal s As String) As String
  Dim h As Double: h = 2166136261#
  Dim prime As Double: prime = 16777619#
  Dim i As Long, c As Long, b As Long
  For i = 1 To Len(s)
    c = AscW(Mid$(s, i, 1)) And &HFFFF&
    b = c And &HFF&: h = (h Xor b): h = h * prime: h = h - (Fix(h / 4294967296#) * 4294967296#)
    b = (c \ 256) And &HFF&: h = (h Xor b): h = h * prime: h = h - (Fix(h / 4294967296#) * 4294967296#)
  Next
  Fnv1a32Hex = ToHex32(h)
End Function

Private Function ToHex32(ByVal v As Double) As String
  Dim i As Long, n As Long, part As Double, tmp As Double
  Dim hexStr As String: hexStr = "": tmp = v
  For i = 1 To 8
    part = tmp - (Fix(tmp / 16#) * 16#)
    n = CLng(part)
    hexStr = Mid$("0123456789abcdef", n + 1, 1) & hexStr
    tmp = Fix(tmp / 16#)
  Next
  ToHex32 = hexStr
End Function
