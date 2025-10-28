Option Explicit
'
' ECM_CA1 ? Simple Panel v3.4e (JA→EN Translator with CSV Dictionary, Shapes support + robust CSV parser)
' - 変更点（v3.4e）:
'   * 【Fix】WarnIfCsvUnsaved を追加（未保存CSVの注意喚起）。Option Explicit 下の未定義エラーを解消。
'
' - 既存（v3.4d）:
'   * 【Fix】CsvFields を PushField 方式で安全化（fields[count] 問題の根治）。
'   * 図形（テキストボックス等）もプレビュー/反映の対象。
'   * プレビュー再実行時、ListObject/フィルタを完全初期化。
'   * FindMarkers で LookIn/SearchOrder を明示し安定化。
'   * CSVは毎回読み込み（キャッシュなし）。失敗時は空Collectionを返す。

' ===== UI定義 =====
Private Const HELPER_SHEET As String = "ECM_Helper"
Private Const COL_WB_PATH As String = "B2"
Private Const COL_CSV_PATH As String = "B3"
Private Const CELL_BACKUP  As String = "B4"
Private Const CELL_STATUS  As String = "B6"

' テーブル
Private Const TABLE_START As String = "A10" ' Include/Sheet/A1/EOL/EOC
Private Const TABLE_NAME  As String = "ECM_Sheets"

' 範囲開始（B2）
Private Const RANGE_START_ROW As Long = 2
Private Const RANGE_START_COL As Long = 2

' 進捗バー
Private Const PROG_BG As String = "ECM_Prog_BG"
Private Const PROG_FG As String = "ECM_Prog_FG"
Private Const SHOW_PROGRESS_BAR As Boolean = True

' シート名
Private Const PREVIEW_SHEET As String = "ECM_Preview"
Private Const LOG_SHEET     As String = "ECM_Log"
Private Const HELP_SHEET    As String = "ECM_Help"

' 配色
Private Const COLOR_PRIMARY       As Long = &HE5464F
Private Const COLOR_PRIMARY_LIGHT As Long = &HFFF2EE
Private Const COLOR_BORDER        As Long = &HCA383F
Private Const COLOR_TEXT          As Long = &H1A1A1A
Private Const COLOR_BUTTON_BG     As Long = &HF5F5F5

' フォント
Private Const UI_FONT As String = "Segoe UI"
Private Const ALT_FONT As String = "Calibri"

' 絵文字
Private Const USE_EMOJI As Boolean = True

' マッチング正規化
Private Const IGNORE_ALL_SPACES_WHEN_MATCHING As Boolean = True
Private Const NORMALIZE_WIDE_NARROW           As Boolean = True

' グローバル（互換のため残置）
Private g_entries As Collection
Private g_loadedDictPath As String
Private g_dictMtime As Date
Private g_dictSize As Double
Private g_dictHash As String

'========================
'          UI
'========================
Public Sub ECM_Setup()
  Application.ScreenUpdating = False
  Application.DisplayAlerts = False

  Dim ws As Worksheet
  Set ws = GetOrCreatePanel(HELPER_SHEET)
  ws.Cells.clear

  With ws.Range("A1")
    .value = LabelWithIcon("globe", "ECM CA1 ? Translate JA → EN")
    .Font.Bold = True
    .Font.Size = 16
    .Font.Color = COLOR_TEXT
    On Error Resume Next
    .Font.Name = IIf(USE_EMOJI, "Segoe UI Emoji", UI_FONT)
    If .Font.Name <> "Segoe UI Emoji" And USE_EMOJI Then .Font.Name = "Segoe UI Symbol"
    If .Font.Name <> "Segoe UI Emoji" And .Font.Name <> "Segoe UI Symbol" Then .Font.Name = ALT_FONT
    On Error GoTo 0
  End With
  ws.Range("A1:F1").Interior.Color = COLOR_PRIMARY_LIGHT
  ws.Rows(1).RowHeight = 28

  ws.Range("A2").value = "Target Workbook (.xlsx/.xlsm):"
  ws.Range(COL_WB_PATH).value = ThisWorkbook.fullName
  ws.Range("A3").value = "Dictionary CSV (source,target,...):"
  ws.Range(COL_CSV_PATH).value = ThisWorkbook.path & Application.PathSeparator & "ECM_JE_Dictionary.csv"

  ws.Range("A4").value = "Backup before apply (Y/N):"
  With ws.Range(CELL_BACKUP)
    .value = "Y"
    With .Validation
      .Delete
      .Add Type:=xlValidateList, AlertStyle:=xlValidAlertStop, Formula1:="Y,N"
      .IgnoreBlank = True
      .InCellDropdown = True
    End With
  End With

  ws.Range("A5").value = "Actions:"
  ws.Range("A6").value = "Status:"
  ws.Range(CELL_STATUS).value = "Ready"

  DeleteButtons ws, "btnECM_*"
  AddButton ws, "btnECM_BrowseWb", LabelWithIcon("folder", "ブック選択"), ws.Range("D2"), 140, "ECM_BrowseWorkbook", True, "対象ブック（翻訳先）を選びます。"
  AddButton ws, "btnECM_OpenWb", LabelWithIcon("search", "開く"), ws.Range("E2"), 100, "ECM_OpenWorkbook", False, "対象ブックを開きます。"
  AddButton ws, "btnECM_BrowseCsv", LabelWithIcon("index", "CSV選択"), ws.Range("D3"), 140, "ECM_BrowseCSV", True, "辞書CSVを選びます。"
  AddButton ws, "btnECM_OpenCsv", LabelWithIcon("search", "開く"), ws.Range("E3"), 100, "ECM_OpenCSV", False, "辞書CSVを開きます。"
  AddButton ws, "btnECM_Scan", LabelWithIcon("compass", "シート検出"), ws.Range("B5"), 120, "ECM_ScanSheets", True, "EOL/EOC 範囲のあるシート一覧。"
  AddButton ws, "btnECM_Preview", LabelWithIcon("flask", "プレビュー"), ws.Range("C5"), 120, "ECM_PreviewTranslations", True, "変更予定を一覧表示。"
  AddButton ws, "btnECM_Apply", LabelWithIcon("check", "反映"), ws.Range("D5"), 120, "ECM_ApplyTranslations", True, "プレビュー内容を反映。"
  AddButton ws, "btnECM_RunAll", LabelWithIcon("play", "おまかせ実行"), ws.Range("E5"), 140, "ECM_RunAll", True, "検出→プレビュー→反映。"

  EnsureProgressBar ws

  AddButton ws, "btnECM_AllY", LabelWithIcon("allok", "すべてY"), ws.Range("B8"), 100, "ECM_SelectAllY", False, "Includeを全てY。"
  AddButton ws, "btnECM_AllN", LabelWithIcon("allng", "すべてN"), ws.Range("C8"), 100, "ECM_SelectAllN", False, "Includeを全てN。"
  AddButton ws, "btnECM_Help", LabelWithIcon("info", "ヘルプ"), ws.Range("D8"), 100, "ECM_OpenHelp", False, "使い方。"
  AddButton ws, "btnECM_Reset", LabelWithIcon("broom", "リセット"), ws.Range("E8"), 100, "ECM_Setup", False, "パネル再作成。"
  AddButton ws, "btnECM_ReloadDict", LabelWithIcon("index", "辞書再読込"), ws.Range("F8"), 120, "ECM_ReloadDictionary", False, "毎回読込方式の説明。"

  SetupIncludeTable ws

  With ws
    .Columns("A").ColumnWidth = 34
    .Columns("B").ColumnWidth = 60
    .Columns("C").ColumnWidth = 28
    .Columns("D").ColumnWidth = 20
    .Columns("E").ColumnWidth = 18
    .Rows(2).RowHeight = 24
    .Rows(3).RowHeight = 24
    .Rows(5).RowHeight = 24
    .Rows(7).RowHeight = 12
    .Rows(8).RowHeight = 24
  End With

  If Not SHOW_PROGRESS_BAR Then
    On Error Resume Next
    ws.Shapes(PROG_BG).Delete
    ws.Shapes(PROG_FG).Delete
    On Error GoTo 0
  End If

  Application.ScreenUpdating = True
  Application.DisplayAlerts = True

  MsgBox "コントロールパネルを作成しました。" & vbCrLf & _
         "1) シート検出 → 2) プレビュー → 3) 反映（推奨: バックアップあり）", vbInformation
End Sub

Private Function GetOrCreatePanel(Name As String) As Worksheet
  Dim ws As Worksheet
  On Error Resume Next
  Set ws = ThisWorkbook.Worksheets(Name)
  On Error GoTo 0
  If ws Is Nothing Then
    Set ws = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.count))
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
    .TextFrame2.TextRange.Font.Size = 10
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

Private Sub SetupIncludeTable(ws As Worksheet)
  Dim lo As ListObject
  On Error Resume Next
  Set lo = ws.ListObjects(TABLE_NAME)
  On Error GoTo 0
  If lo Is Nothing Then
    ws.Range(TABLE_START).Resize(1, 5).value = Array("Include (Y/N)", "Sheet", "A1", "EOL", "EOC")
    Dim tgt As Range
    Set tgt = ws.Range(TABLE_START).Resize(2, 5) ' header + 1 blank row
    Set lo = ws.ListObjects.Add(xlSrcRange, tgt, , xlYes)
    lo.Name = TABLE_NAME
    lo.TableStyle = "TableStyleLight11"
    If Not lo.DataBodyRange Is Nothing Then lo.DataBodyRange.Rows.Delete
  Else
    lo.HeaderRowRange.value = Array("Include (Y/N)", "Sheet", "A1", "EOL", "EOC")
  End If
  With ws.Range("A11:A10000").Validation
    .Delete
    .Add Type:=xlValidateList, AlertStyle:=xlValidAlertStop, Formula1:="Y,N"
  End With
End Sub

'========================
'   プログレス（UI）
'========================
Private Sub EnsureProgressBar(ws As Worksheet)
  If Not SHOW_PROGRESS_BAR Then Exit Sub

  Dim topCell As Range: Set topCell = ws.Range("B7")
  Dim widthTotal As Double: widthTotal = ws.Range("B7:E7").Width
  Dim h As Double: h = ws.Rows(7).RowHeight - 2

  On Error Resume Next
  ws.Shapes(PROG_BG).Delete
  ws.Shapes(PROG_FG).Delete
  On Error GoTo 0

  Dim bg As Shape, fg As Shape
  Set bg = ws.Shapes.AddShape(msoShapeRectangle, topCell.Left, topCell.Top + 1, widthTotal, h)
  With bg
    .Name = PROG_BG
    .Fill.ForeColor.RGB = RGB(240, 240, 240)
    .line.Visible = msoFalse
  End With

  Set fg = ws.Shapes.AddShape(msoShapeRectangle, topCell.Left, topCell.Top + 1, 0, h)
  With fg
    .Name = PROG_FG
    .Fill.ForeColor.RGB = COLOR_PRIMARY
    .line.Visible = msoFalse
  End With
End Sub

Private Sub SetProgress(ByVal percent As Double, Optional ByVal caption As String = "")
  If Not SHOW_PROGRESS_BAR Then
    If Len(caption) > 0 Then SetStatus caption
    Application.StatusBar = caption
    Exit Sub
  End If
  Dim ws As Worksheet: On Error Resume Next: Set ws = ThisWorkbook.Worksheets(HELPER_SHEET): On Error GoTo 0
  If ws Is Nothing Then Exit Sub
  Dim bg As Shape, fg As Shape
  On Error Resume Next
  Set bg = ws.Shapes(PROG_BG): Set fg = ws.Shapes(PROG_FG)
  On Error GoTo 0
  If bg Is Nothing Or fg Is Nothing Then Exit Sub
  If percent < 0 Then percent = 0
  If percent > 1 Then percent = 1
  fg.Width = bg.Width * percent
  If Len(caption) > 0 Then SetStatus caption
  Application.StatusBar = caption
End Sub

Private Sub ResetProgress()
  SetProgress 0, "Ready"
  Application.StatusBar = False
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
    .Filters.clear
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
    .Filters.clear
    .Filters.Add "CSV", "*.csv"
    If .Show = -1 Then ws.Range(COL_CSV_PATH).value = .SelectedItems(1)
  End With
End Sub

Public Sub ECM_OpenWorkbook()
  Dim path As String: path = CleanPath(ThisWorkbook.Worksheets(HELPER_SHEET).Range(COL_WB_PATH).value & "")
  If Len(path) > 0 And Dir$(path) <> "" Then
    Application.Workbooks.Open path
  Else
    MsgBox "Invalid workbook path.", vbExclamation
  End If
End Sub

Public Sub ECM_OpenCSV()
  Dim path As String: path = CleanPath(ThisWorkbook.Worksheets(HELPER_SHEET).Range(COL_CSV_PATH).value & "")
  If Len(path) > 0 And Dir$(path) <> "" Then
    Application.Workbooks.Open path
  Else
    MsgBox "Invalid CSV path.", vbExclamation
  End If
End Sub

'========================
'        検出/集計
'========================
Public Sub ECM_ScanSheets()
  Dim wsUI As Worksheet: Set wsUI = ThisWorkbook.Worksheets(HELPER_SHEET)
  Dim wb As Workbook: Set wb = GetTargetWorkbook(wsUI.Range(COL_WB_PATH).value & "")
  If wb Is Nothing Then
    MsgBox "Could not open target workbook.", vbExclamation
    Exit Sub
  End If

  Dim lo As ListObject: Set lo = wsUI.ListObjects(TABLE_NAME)
  On Error Resume Next
  Do While lo.ListRows.count > 0: lo.ListRows(1).Delete: Loop
  On Error GoTo 0

  Application.ScreenUpdating = False
  SetStatus "Scanning sheets..."
  SetProgress 0

  Dim sh As Worksheet, eolRow As Long, eocCol As Long
  Dim total As Long: total = wb.Worksheets.count
  Dim i As Long: i = 0

  For Each sh In wb.Worksheets
    i = i + 1
    If FindMarkers(sh, eolRow, eocCol) Then
      Dim nr As ListRow
      Set nr = lo.ListRows.Add
      nr.Range(1, 1).value = "Y"
      nr.Range(1, 2).value = sh.Name
      nr.Range(1, 3).value = SafeText(sh.Range("A1").Value2)
      nr.Range(1, 4).value = eolRow
      nr.Range(1, 5).value = eocCol
    End If
    If (i Mod 1) = 0 Then SetProgress i / total, "Scanning: " & i & "/" & total
  Next

  ResetProgress
  Application.ScreenUpdating = True
  SetStatus "Scan complete."
  MsgBox "シート検出が完了しました。処理対象に 'Y' を付けてください。", vbInformation
End Sub

Public Sub ECM_ExportTemplate()
  Dim wsUI As Worksheet: Set wsUI = ThisWorkbook.Worksheets(HELPER_SHEET)
  Dim wb As Workbook: Set wb = GetTargetWorkbook(wsUI.Range(COL_WB_PATH).value & "")
  If wb Is Nothing Then
    MsgBox "Could not open target workbook.", vbExclamation
    Exit Sub
  End If

  Dim uniq As Object: Set uniq = CreateObject("Scripting.Dictionary")
  uniq.CompareMode = 1 'TextCompare

  Dim lo As ListObject: Set lo = wsUI.ListObjects(TABLE_NAME)
  Dim r As Long
  For r = 1 To lo.ListRows.count
    If UCase$(Trim$(lo.DataBodyRange(r, 1).value & "")) = "Y" Then
      Dim shName As String: shName = lo.DataBodyRange(r, 2).value & ""
      If Len(shName) > 0 Then
        Dim ws As Worksheet: Set ws = Nothing
        On Error Resume Next: Set ws = wb.Worksheets(shName): On Error GoTo 0
        If Not ws Is Nothing Then CollectLabels ws, uniq
        ' 図形も集めたい場合は、FindMarkers→範囲→CollectTextShapes→GetShapeText→uniq.Add を追加
      End If
    End If
  Next

  Dim outWb As Workbook: Set outWb = Application.Workbooks.Add(xlWBATWorksheet)
  Dim outWs As Worksheet: Set outWs = outWb.Worksheets(1)
  outWs.Name = "Dictionary"
  outWs.Range("A1").value = "source"
  outWs.Range("B1").value = "target"

  Dim key As Variant, rowOut As Long: rowOut = 2
  For Each key In uniq.Keys
    outWs.Cells(rowOut, 1).value = key
    outWs.Cells(rowOut, 2).value = ""
    rowOut = rowOut + 1
  Next
  outWs.Columns("A:B").AutoFit

  Dim savePath As String
  savePath = ThisWorkbook.path & Application.PathSeparator & "ECM_JE_Dictionary.csv"
  On Error Resume Next
  outWb.SaveAs Filename:=savePath, FileFormat:=xlCSVUTF8, Local:=True
  outWb.Close SaveChanges:=False
  On Error GoTo 0

  MsgBox "テンプレートを出力しました: " & savePath, vbInformation
End Sub

'========================
'     プレビュー/反映
'========================
Public Sub ECM_PreviewTranslations()
  Dim wsUI As Worksheet: Set wsUI = ThisWorkbook.Worksheets(HELPER_SHEET)
  Dim wb As Workbook: Set wb = GetTargetWorkbook(wsUI.Range(COL_WB_PATH).value & "")
  If wb Is Nothing Then
    MsgBox "Could not open target workbook.", vbExclamation
    Exit Sub
  End If

  Dim csvPath As String: csvPath = CleanPath(wsUI.Range(COL_CSV_PATH).value & "")
  If Len(csvPath) = 0 Then
    MsgBox "Please set Dictionary CSV path.", vbExclamation: Exit Sub
  End If

  WarnIfCsvUnsaved csvPath

  SetStatus "Loading dictionary..."
  Dim entries As Collection
  Set entries = EnsureDictionaryLoaded(csvPath)
  If (entries Is Nothing) Or (entries.count = 0) Then
    SetStatus "Dictionary load failed or empty."
    MsgBox "辞書が読み込めませんでした（空か、形式不正）。", vbExclamation
    Exit Sub
  End If
  SetStatus "Dictionary loaded: " & entries.count & " entries"

  Application.ScreenUpdating = False
  Application.StatusBar = "Preview..."
  SetProgress 0, "Preview..."

  Dim rep As Worksheet: Set rep = GetOrCreateSheet(PREVIEW_SHEET, True) ' 完全初期化
  rep.Range("A1:E1").value = Array("Sheet", "Cell", "Before", "After", "Scope")
  rep.Range("A1:E1").Font.Bold = True

  Dim lo As ListObject: Set lo = wsUI.ListObjects(TABLE_NAME)
  Dim out As New Collection
  Dim totalMatches As Long, totalChanges As Long, totalScanned As Long

  Dim i As Long, totalSheets As Long: totalSheets = lo.ListRows.count
  For i = 1 To lo.ListRows.count
    If UCase$(Trim$(lo.DataBodyRange(i, 1).value & "")) <> "Y" Then GoTo ContinueSheet
    Dim shName As String: shName = lo.DataBodyRange(i, 2).value & ""
    If Len(shName) = 0 Then GoTo ContinueSheet

    Dim ws As Worksheet: Set ws = Nothing
    On Error Resume Next: Set ws = wb.Worksheets(shName): On Error GoTo 0
    If ws Is Nothing Then GoTo ContinueSheet
    If SheetProtected(ws) Then GoTo ContinueSheet

    Dim idx As Object: Set idx = BuildIndexForSheet(entries, ws)
    Dim eolRow As Long, eocCol As Long
    If Not FindMarkers(ws, eolRow, eocCol) Then GoTo ContinueSheet

    Dim textRng As Range: Set textRng = GetTextCellsRange(ws, eolRow, eocCol)
    If Not textRng Is Nothing Then
      Dim cell As Range, key As String
      For Each cell In textRng.Cells
        totalScanned = totalScanned + 1
        If VarType(cell.Value2) = vbString Then
          key = KeyFor(CStr(cell.Value2))
          If Len(key) > 0 And idx.Exists(key) Then
            totalMatches = totalMatches + 1
            Dim entry As Object: Set entry = idx.Item(key)
            Dim tgt As String: tgt = CStr(entry.Item("target"))
            If CStr(cell.Value2) <> tgt Then
              totalChanges = totalChanges + 1
              Dim rec(1 To 5) As Variant
              rec(1) = ws.Name
              rec(2) = cell.Address(False, False)
              rec(3) = CStr(cell.Value2)
              rec(4) = tgt
              rec(5) = entry.Item("scope") & ""
              out.Add rec
            End If
          End If
        End If
      Next
    End If

    ' 図形のプレビュー
    Dim targetRect As Range
    Set targetRect = ws.Range(ws.Cells(RANGE_START_ROW, RANGE_START_COL), ws.Cells(eolRow, eocCol))

    Dim shapesInScope As New Collection, shp As Shape
    CollectTextShapes ws.Shapes, targetRect, shapesInScope

    For Each shp In shapesInScope
      Dim sTxt As String: sTxt = GetShapeText(shp)
      If Len(sTxt) > 0 Then
        Dim key2 As String: key2 = KeyFor(sTxt)
        If Len(key2) > 0 And idx.Exists(key2) Then
          Dim e As Object: Set e = idx.Item(key2)
          Dim t As String: t = CStr(e.Item("target"))
          If sTxt <> t Then
            totalMatches = totalMatches + 1
            totalChanges = totalChanges + 1
            Dim rec2(1 To 5) As Variant
            rec2(1) = ws.Name
            rec2(2) = "Shape:" & shp.Name
            rec2(3) = sTxt
            rec2(4) = t
            rec2(5) = e.Item("scope") & ""
            out.Add rec2
          End If
        End If
      End If
    Next

ContinueSheet:
    SetProgress i / IIf(totalSheets = 0, 1, totalSheets), "Preview " & i & "/" & totalSheets
  Next

  If out.count > 0 Then
    Dim arr() As Variant: ReDim arr(1 To out.count, 1 To 5)
    Dim r As Long
    For r = 1 To out.count
      Dim rowArr As Variant: rowArr = out(r)
      arr(r, 1) = rowArr(1)
      arr(r, 2) = rowArr(2)
      arr(r, 3) = rowArr(3)
      arr(r, 4) = rowArr(4)
      arr(r, 5) = rowArr(5)
    Next
    rep.Range("A2").Resize(UBound(arr, 1), 5).value = arr
  End If

  CreateTableIfNeeded rep, "A1:E1", "A2"
  rep.Columns("A:E").AutoFit
  rep.Activate
  Application.GoTo rep.Range("A1"), True
  On Error Resume Next
  With ActiveWindow
    .FreezePanes = False
    .SplitColumn = 0
    .SplitRow = 0
  End With
  On Error GoTo 0

  ResetProgress
  Application.ScreenUpdating = True
  SetStatus "Preview: " & totalChanges & " changes (" & totalMatches & " matches, scanned " & totalScanned & ")"
  MsgBox "プレビューを作成しました。'" & PREVIEW_SHEET & "' をご確認ください。" & vbCrLf & _
         "変更予定セル/図形数: " & totalChanges, vbInformation
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
    MsgBox "Please set Dictionary CSV path.", vbExclamation: Exit Sub
  End If

  WarnIfCsvUnsaved csvPath

  SetStatus "Loading dictionary..."
  Dim entries As Collection
  Set entries = EnsureDictionaryLoaded(csvPath)
  If (entries Is Nothing) Or (entries.count = 0) Then
    SetStatus "Dictionary load failed or empty."
    MsgBox "辞書が読み込めませんでした（空か、形式不正）。", vbExclamation
    Exit Sub
  End If
  SetStatus "Dictionary loaded: " & entries.count & " entries"

  If UCase$(Trim$(wsUI.Range(CELL_BACKUP).value & "")) = "Y" Then
    On Error Resume Next
    Dim bk As String: bk = BackupPath(wb.fullName)
    wb.SaveCopyAs bk
    On Error GoTo 0
  End If

  If MsgBox("プレビューの内容を反映します。" & vbCrLf & _
            "・対象ブック: " & wb.Name & vbCrLf & _
            "・辞書: " & csvPath & vbCrLf & _
            "・バックアップ: " & IIf(UCase$(Trim$(wsUI.Range(CELL_BACKUP).value & "")) = "Y", "あり", "なし") & vbCrLf & _
            "よろしいですか？", vbQuestion + vbOKCancel) <> vbOK Then
    Exit Sub
  End If

  Application.ScreenUpdating = False
  Application.Calculation = xlCalculationManual
  Application.EnableEvents = False
  Application.StatusBar = "Applying translations..."
  SetProgress 0, "Applying..."

  Dim lo As ListObject: Set lo = wsUI.ListObjects(TABLE_NAME)
  Dim i As Long, totalApplied As Long, totalSheets As Long: totalSheets = lo.ListRows.count
  Dim changes As New Collection

  For i = 1 To lo.ListRows.count
    If UCase$(Trim$(lo.DataBodyRange(i, 1).value & "")) <> "Y" Then GoTo NextSheet
    Dim shName As String: shName = lo.DataBodyRange(i, 2).value & ""
    If Len(shName) = 0 Then GoTo NextSheet

    Dim ws As Worksheet: Set ws = Nothing
    On Error Resume Next: Set ws = wb.Worksheets(shName): On Error GoTo 0
    If ws Is Nothing Then GoTo NextSheet
    If SheetProtected(ws) Then GoTo NextSheet

    totalApplied = totalApplied + ApplyToSheet(ws, entries, changes)

NextSheet:
    SetProgress i / IIf(totalSheets = 0, 1, totalSheets), "Applying " & i & "/" & totalSheets
  Next

  If changes.count > 0 Then WriteChangeLog changes, csvPath

  Application.StatusBar = False
  Application.EnableEvents = True
  Application.Calculation = xlCalculationAutomatic
  Application.ScreenUpdating = True
  ResetProgress

  MsgBox "反映が完了しました。変更セル/図形数: " & totalApplied & vbCrLf & "保存してください。", vbInformation
End Sub

'========================
'  ワンボタン実行 / ヘルプ
'========================
Public Sub ECM_RunAll()
  ECM_ScanSheets
  ECM_PreviewTranslations
  ECM_ApplyTranslations
End Sub

Public Sub ECM_OpenHelp()
  Dim ws As Worksheet: Set ws = GetOrCreateSheet(HELP_SHEET, False)
  With ws
    .Cells.clear
    .Range("A1").value = LabelWithIcon("info", "ECM CA1 ? ヘルプ")
    .Range("A1").Font.Bold = True
    .Range("A1").Font.Size = 16
    .Range("A2").value = "目的：辞書CSVでEOL/EOC範囲のセル定数＋図形テキストを英訳。scopeで対象絞り込み可。"
    .Range("A4").value = "手順：Setup → パス設定 → 検出 → プレビュー → 反映（推奨：バックアップ）"
    .Range("A6").value = "CSV列：source, target, scope, font_name, font_size, align, bold（ヘッダ名で判定）"
    .Range("A7").value = "正規化：空白無視/全角→半角/括弧統一/ダッシュ統一。重複定義は後勝ち。"
    .Columns("A").EntireColumn.AutoFit
  End With
  ws.Activate
  MsgBox "ヘルプを表示しました。", vbInformation
End Sub

'========================
'    手動: 辞書キャッシュクリア（説明のみ）
'========================
Public Sub ECM_ReloadDictionary()
  g_loadedDictPath = ""
  Set g_entries = Nothing
  g_dictMtime = 0
  g_dictSize = 0
  g_dictHash = ""
  SetStatus "（毎回読込方式）辞書は各実行時に最新を読み込みます。"
  MsgBox "更新検知/キャッシュは廃止。毎回CSVを読み込みます。", vbInformation
End Sub

'========================
'    Include 一括操作
'========================
Public Sub ECM_SelectAllY(): ECM_SelectAllInclude "Y": End Sub
Public Sub ECM_SelectAllN(): ECM_SelectAllInclude "N": End Sub
Private Sub ECM_SelectAllInclude(ByVal mark As String)
  Dim ws As Worksheet: Set ws = ThisWorkbook.Worksheets(HELPER_SHEET)
  Dim lo As ListObject: Set lo = ws.ListObjects(TABLE_NAME)
  If lo.ListRows.count = 0 Then Exit Sub
  lo.DataBodyRange.Columns(1).value = mark
End Sub

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
  Set wb = Application.Workbooks.Open(Filename:=path, ReadOnly:=False)
  On Error GoTo 0
  Set GetTargetWorkbook = wb
End Function

Private Function FindMarkers(ws As Worksheet, ByRef eolRow As Long, ByRef eocCol As Long) As Boolean
  Dim c As Range, r As Range
  Dim searchRow As Range, searchCol As Range
  Set searchRow = ws.Rows(1)
  Set searchCol = ws.Columns(1)
  On Error Resume Next
  Set c = searchRow.Find(What:="EOC", _
                         After:=searchRow.Cells(searchRow.Columns.count), _
                         LookIn:=xlValues, LookAt:=xlWhole, _
                         SearchOrder:=xlByColumns, SearchDirection:=xlNext, _
                         MatchCase:=False)
  Set r = searchCol.Find(What:="EOL", _
                         After:=searchCol.Cells(searchCol.Rows.count), _
                         LookIn:=xlValues, LookAt:=xlWhole, _
                         SearchOrder:=xlByRows, SearchDirection:=xlNext, _
                         MatchCase:=False)
  On Error GoTo 0
  If c Is Nothing Or r Is Nothing Then Exit Function
  eocCol = c.Column
  eolRow = r.Row
  FindMarkers = True
End Function

Private Function GetTextCellsRange(ws As Worksheet, ByVal eolRow As Long, ByVal eocCol As Long) As Range
  Dim baseRng As Range, visRng As Range, textRng As Range
  Set baseRng = ws.Range(ws.Cells(RANGE_START_ROW, RANGE_START_COL), ws.Cells(eolRow, eocCol))
  On Error Resume Next
  Set visRng = baseRng.SpecialCells(xlCellTypeVisible)
  If visRng Is Nothing Then Set visRng = baseRng
  Set textRng = visRng.SpecialCells(xlCellTypeConstants, xlTextValues)
  On Error GoTo 0
  Set GetTextCellsRange = textRng
End Function

Private Sub CollectLabels(ws As Worksheet, ByRef uniq As Object)
  Dim eolRow As Long, eocCol As Long
  If Not FindMarkers(ws, eolRow, eocCol) Then Exit Sub
  Dim textRng As Range: Set textRng = GetTextCellsRange(ws, eolRow, eocCol)
  If textRng Is Nothing Then Exit Sub
  Dim cell As Range, v As Variant
  For Each cell In textRng.Cells
    v = cell.Value2
    If VarType(v) = vbString Then
      v = Trim$(CStr(v))
      If Len(v) > 0 Then If Not uniq.Exists(v) Then uniq.Add v, 1
    End If
  Next
End Sub

Private Function SheetProtected(ws As Worksheet) As Boolean
  On Error Resume Next
  SheetProtected = ws.ProtectContents
  On Error GoTo 0
End Function

' 適用（戻り値: 変更セル/図形数）＋ 変更ログ収集（Optional changes）
Private Function ApplyToSheet(ws As Worksheet, entries As Collection, Optional changes As Collection) As Long
  Dim eolRow As Long, eocCol As Long
  If Not FindMarkers(ws, eolRow, eocCol) Then Exit Function
  Dim textRng As Range: Set textRng = GetTextCellsRange(ws, eolRow, eocCol)
  On Error Resume Next
  If Not textRng Is Nothing Then textRng.Font.Name = "Arial"
  On Error GoTo 0

  Dim idx As Object: Set idx = BuildIndexForSheet(entries, ws)
  Dim cell As Range, key As String, changed As Long, entry As Object
  Dim total As Long
  If textRng Is Nothing Then
    total = 0
  Else
    total = textRng.Cells.count
  End If
  Dim i As Long: i = 0

  If Not textRng Is Nothing Then
    For Each cell In textRng.Cells
      i = i + 1
      If (i Mod 200) = 0 Then Application.StatusBar = "Applying " & ws.Name & "... (" & i & "/" & total & ")"
      If VarType(cell.Value2) = vbString Then
        key = KeyFor(CStr(cell.Value2))
        If Len(key) > 0 And idx.Exists(key) Then
          Set entry = idx.Item(key)
          If CStr(cell.Value2) <> CStr(entry.Item("target")) Then
            Dim beforeVal As String: beforeVal = CStr(cell.Value2)
            cell.Value2 = entry.Item("target")
            ApplyStyleIfAny cell, entry
            changed = changed + 1
            If Not changes Is Nothing Then
              Dim rec(1 To 5) As Variant
              rec(1) = ws.Name
              rec(2) = cell.Address(False, False)
              rec(3) = beforeVal
              rec(4) = CStr(entry.Item("target"))
              rec(5) = entry.Item("scope") & ""
              changes.Add rec
            End If
          End If
        End If
      End If
    Next
  End If

  ' 図形の反映
  Dim targetRect As Range
  Set targetRect = ws.Range(ws.Cells(RANGE_START_ROW, RANGE_START_COL), ws.Cells(eolRow, eocCol))

  Dim shapesInScope As New Collection, shp As Shape
  CollectTextShapes ws.Shapes, targetRect, shapesInScope

  For Each shp In shapesInScope
    Dim sTxt As String: sTxt = GetShapeText(shp)
    If Len(sTxt) > 0 Then
      key = KeyFor(sTxt)
      If Len(key) > 0 And idx.Exists(key) Then
        Set entry = idx.Item(key)
        Dim tgt As String: tgt = CStr(entry.Item("target"))
        If sTxt <> tgt Then
          SetShapeText shp, tgt
          ApplyShapeStyleIfAny shp, entry
          changed = changed + 1
          If Not changes Is Nothing Then
            Dim recS(1 To 5) As Variant
            recS(1) = ws.Name
            recS(2) = "Shape:" & shp.Name
            recS(3) = sTxt
            recS(4) = tgt
            recS(5) = entry.Item("scope") & ""
            changes.Add recS
          End If
        End If
      End If
    End If
  Next

  Application.StatusBar = False
  ApplyToSheet = changed
End Function

Private Sub ApplyStyleIfAny(ByVal cell As Range, ByVal entry As Object)
  On Error Resume Next
  Dim fn As String: fn = entry.Item("font_name") & ""
  If Len(fn) > 0 Then cell.Font.Name = fn

  Dim fs As Variant: fs = entry.Item("font_size")
  If Not IsEmpty(fs) And Len(Trim$(fs & "")) > 0 Then
    If IsNumeric(fs) Then cell.Font.Size = CDbl(fs)
  End If

  Dim b As Variant: b = entry.Item("bold")
  If Not IsEmpty(b) And Len(Trim$(b & "")) > 0 Then
    cell.Font.Bold = (UCase$(CStr(b)) = "1" Or UCase$(CStr(b)) = "TRUE")
  End If

  Dim al As String: al = LCase$(Trim$(entry.Item("align") & ""))
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
  Dim rLeft As Double, rTop As Double, rRight As Double, rBottom As Double
  rLeft = rng.Left
  rTop = rng.Top
  rRight = rLeft + rng.Width
  rBottom = rTop + rng.Height

  Dim sLeft As Double, sTop As Double, sRight As Double, sBottom As Double
  sLeft = shp.Left
  sTop = shp.Top
  sRight = sLeft + shp.Width
  sBottom = sTop + shp.Height

  ' Overlap check with small tolerance to account for floating point rounding
  Const EPS As Double = 0.5
  If sRight < rLeft - EPS Then GoTo EH
  If sLeft > rRight + EPS Then GoTo EH
  If sBottom < rTop - EPS Then GoTo EH
  If sTop > rBottom + EPS Then GoTo EH
  ShapeInRange = True
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
  Dim fn As String: fn = entry.Item("font_name") & ""
  If Len(fn) > 0 Then shp.TextFrame2.TextRange.Font.Name = fn

  Dim fs As Variant: fs = entry.Item("font_size")
  If Not IsEmpty(fs) And Len(Trim$(fs & "")) > 0 Then
    If IsNumeric(fs) Then shp.TextFrame2.TextRange.Font.Size = CDbl(fs)
  End If

  Dim b As Variant: b = entry.Item("bold")
  If Not IsEmpty(b) And Len(Trim$(b & "")) > 0 Then
    shp.TextFrame2.TextRange.Font.Bold = IIf(UCase$(CStr(b)) = "1" Or UCase$(CStr(b)) = "TRUE", msoTrue, msoFalse)
  End If

  Dim al As String: al = LCase$(Trim$(entry.Item("align") & ""))
  Select Case al
    Case "left":   shp.TextFrame2.TextRange.ParagraphFormat.Alignment = msoAlignLeft
    Case "center", "centre": shp.TextFrame2.TextRange.ParagraphFormat.Alignment = msoAlignCenter
    Case "right":  shp.TextFrame2.TextRange.ParagraphFormat.Alignment = msoAlignRight
  End Select
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

  Dim loaded As Collection
  Set loaded = LoadDictionaryFromCSV(cleaned)

  If loaded Is Nothing Then
    SetStatus "Dictionary load failed (empty or format error): " & cleaned
    Set EnsureDictionaryLoaded = New Collection
  Else
    Set EnsureDictionaryLoaded = loaded
  End If
End Function

Private Function LoadDictionaryFromCSV(ByVal csvPath As String) As Collection
  csvPath = CleanPath(csvPath)

  Dim cUtf8 As Collection, cExcel As Collection
  Set cUtf8 = ParseCsvFile(csvPath)            ' UTF-8直読
  Set cExcel = LoadDictionaryViaExcel(csvPath) ' Excel経由

  Dim idx As Object: Set idx = CreateObject("Scripting.Dictionary")
  idx.CompareMode = 1

  Dim e As Variant, k As String

  If Not cExcel Is Nothing Then
    For Each e In cExcel
      k = KeyFor(CStr(e.Item("source")))
      If Len(k) > 0 Then
        If idx.Exists(k) Then idx.Remove k
        idx.Add k, e
      End If
    Next
  End If

  If Not cUtf8 Is Nothing Then
    For Each e In cUtf8
      k = KeyFor(CStr(e.Item("source")))
      If Len(k) > 0 Then
        If idx.Exists(k) Then idx.Remove k
        idx.Add k, e
      End If
    Next
  End If

  Dim out As New Collection, key As Variant
  For Each key In idx.Keys: out.Add idx(key): Next
  Set LoadDictionaryFromCSV = out
End Function

Private Function LoadDictionaryViaExcel(ByVal csvPath As String) As Collection
  On Error GoTo ErrExcel
  Dim out As New Collection
  Dim csvWb As Workbook: Set csvWb = Application.Workbooks.Open(Filename:=csvPath, ReadOnly:=True, Local:=True)
  Dim ws As Worksheet: Set ws = csvWb.Worksheets(1)

  Dim headerMap As Object: Set headerMap = CreateObject("Scripting.Dictionary")
  headerMap.CompareMode = 1
  Dim lastCol As Long: lastCol = ws.Cells(1, 1).CurrentRegion.Columns.count
  If lastCol = 1 Then lastCol = ws.Cells(1, ws.Columns.count).End(xlToLeft).Column

  Dim c As Long, h As String
  For c = 1 To lastCol
    h = LCase$(Trim$(SafeText(ws.Cells(1, c).Value2)))
    If Len(h) > 0 Then headerMap(h) = c
  Next

  Dim colSource As Long, colTarget As Long
  Dim colScope As Long, colFontName As Long, colFontSize As Long, colAlign As Long, colBold As Long
  colSource = Nz(headerMap("source"), 1)
  colTarget = Nz(headerMap("target"), 2)
  colScope = Nz(headerMap("scope"), 0)
  colFontName = Nz(headerMap("font_name"), 0)
  colFontSize = Nz(headerMap("font_size"), 0)
  colAlign = Nz(headerMap("align"), 0)
  colBold = Nz(headerMap("bold"), 0)

  Dim lastRow As Long: lastRow = ws.Cells(1, 1).CurrentRegion.Rows.count
  If lastRow < 2 Then lastRow = ws.Cells(ws.Rows.count, 1).End(xlUp).Row

  Dim r As Long
  For r = 2 To lastRow
    Dim src As String: src = Trim$(SafeText(ws.Cells(r, colSource).Value2))
    If Len(src) = 0 Then GoTo NextR
    Dim e As Object: Set e = CreateObject("Scripting.Dictionary")
    e.Add "scope", IIf(colScope > 0, Trim$(SafeText(ws.Cells(r, colScope).Value2)), "")
    e.Add "source", src
    e.Add "target", Trim$(SafeText(ws.Cells(r, colTarget).Value2))
    e.Add "font_name", IIf(colFontName > 0, SafeText(ws.Cells(r, colFontName).Value2), "")
    e.Add "font_size", IIf(colFontSize > 0, SafeText(ws.Cells(r, colFontSize).Value2), "")
    e.Add "align", IIf(colAlign > 0, SafeText(ws.Cells(r, colAlign).Value2), "")
    e.Add "bold", IIf(colBold > 0, SafeText(ws.Cells(r, colBold).Value2), "")
    out.Add e
NextR:
  Next
  csvWb.Close SaveChanges:=False
  Set LoadDictionaryViaExcel = out
  Exit Function

ErrExcel:
  On Error Resume Next
  If Not csvWb Is Nothing Then csvWb.Close SaveChanges:=False
  Set LoadDictionaryViaExcel = Nothing
End Function

'========================
'  CSV UTF-8 直読 + パース
'========================
Private Function ParseCsvFile(ByVal csvPath As String) As Collection
  On Error GoTo ErrH
  If Len(Dir$(csvPath)) = 0 Then Exit Function
  Dim text As String: text = ReadAllTextUTF8(csvPath)
  If Len(text) = 0 Then Exit Function
  text = Replace(Replace(text, vbCrLf, vbLf), vbCr, vbLf)
  Dim lines() As String: lines = Split(text, vbLf)

  Dim colSource As Long, colTarget As Long
  Dim colScope As Long, colFontName As Long, colFontSize As Long, colAlign As Long, colBold As Long
  colSource = -1: colTarget = -1: colScope = -1: colFontName = -1: colFontSize = -1: colAlign = -1: colBold = -1

  Dim out As New Collection
  Dim i As Long, fields As Variant, headerDone As Boolean

  ' ヘッダ解析
  For i = LBound(lines) To UBound(lines)
    If Len(Trim$(lines(i))) = 0 Then GoTo NextLine
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
      If h = "scope" Then colScope = j
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

  For i = startRow To UBound(lines)
    If Len(Trim$(lines(i))) = 0 Then GoTo NextData
    fields = CsvFields(lines(i))
    If UBound(fields) < colTarget Then GoTo NextData
    Dim src As String: src = Trim$(CStr(fields(colSource)))
    If Len(src) = 0 Then GoTo NextData
    Dim e As Object: Set e = CreateObject("Scripting.Dictionary")
    e.Add "scope", FieldOrEmpty(fields, colScope)
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
  Exit Function
ErrH:
  Set ParseCsvFile = Nothing
End Function

Private Function FieldOrEmpty(ByVal fields As Variant, ByVal idx As Long) As String
  If idx >= 0 And idx <= UBound(fields) Then FieldOrEmpty = CStr(fields(idx)) Else FieldOrEmpty = ""
End Function

' --- UTF-8 読み込み（ADODB.Stream） ---
Private Function ReadAllTextUTF8(ByVal path As String) As String
  On Error GoTo Fallback
  Dim stm As Object: Set stm = CreateObject("ADODB.Stream")
  stm.Type = 2: stm.Mode = 3: stm.Charset = "utf-8"
  stm.Open: stm.LoadFromFile path
  ReadAllTextUTF8 = stm.ReadText(-1)
  stm.Close: Set stm = Nothing
  Exit Function
Fallback:
  On Error Resume Next
  Dim fso As Object, ts As Object
  Set fso = CreateObject("Scripting.FileSystemObject")
  If fso.FileExists(path) Then
    Set ts = fso.OpenTextFile(path, 1, False)
    ReadAllTextUTF8 = ts.ReadAll
    ts.Close
  Else
    ReadAllTextUTF8 = ""
  End If
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
Private Function BuildIndexForSheet(entries As Collection, ws As Worksheet) As Object
  Dim idx As Object: Set idx = CreateObject("Scripting.Dictionary")
  idx.CompareMode = 1
  Dim entry As Variant, k As String
  For Each entry In entries
    If ShouldApplyToSheet(entry, ws) Then
      k = KeyFor(CStr(entry.Item("source")))
      If Len(k) > 0 Then
        If idx.Exists(k) Then idx.Remove k
        idx.Add k, entry
      End If
    End If
  Next
  Set BuildIndexForSheet = idx
End Function

Private Function ShouldApplyToSheet(ByVal entry As Object, ByVal ws As Worksheet) As Boolean
  Dim scope As String: scope = Trim$(entry.Item("scope") & "")
  If Len(scope) = 0 Then ShouldApplyToSheet = True: Exit Function
  Dim a1 As String: a1 = SafeText(ws.Range("A1").Value2)
  If InStr(1, ws.Name, scope, vbTextCompare) > 0 Then
    ShouldApplyToSheet = True
  ElseIf InStr(1, a1, scope, vbTextCompare) > 0 Then
    ShouldApplyToSheet = True
  Else
    ShouldApplyToSheet = False
  End If
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

Private Function Nz(ByVal v As Variant, ByVal def As Long) As Long
  If IsEmpty(v) Or IsNull(v) Then
    Nz = def
  ElseIf VarType(v) = vbString Then
    If Len(Trim$(CStr(v))) = 0 Then Nz = def Else Nz = CLng(v)
  Else
    Nz = CLng(v)
  End If
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
  On Error Resume Next
  ThisWorkbook.Worksheets(HELPER_SHEET).Range(CELL_STATUS).value = msg
  On Error GoTo 0
End Sub

'========================
'   テーブル/ログ/ユーティリティ
'========================
Private Function GetOrCreateSheet(ByVal Name As String, ByVal clear As Boolean) As Worksheet
  Dim ws As Worksheet
  On Error Resume Next
  Set ws = ThisWorkbook.Worksheets(Name)
  On Error GoTo 0
  If ws Is Nothing Then
    Set ws = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.count))
    ws.Name = Name
  ElseIf clear Then
    On Error Resume Next
    If ws.AutoFilterMode Then ws.AutoFilterMode = False
    Dim lo As ListObject
    For Each lo In ws.ListObjects
      lo.Delete
    Next
    ws.Cells.clear
    On Error GoTo 0
  End If
  Set GetOrCreateSheet = ws
End Function

Private Sub CreateTableIfNeeded(ByVal ws As Worksheet, ByVal headerRangeAddress As String, ByVal dataStartCellAddress As String)
  Dim lo As ListObject
  On Error Resume Next
  Set lo = ws.ListObjects(1)
  On Error GoTo 0
  If Not lo Is Nothing Then Exit Sub

  Dim lastRow As Long: lastRow = ws.Cells(ws.Rows.count, ws.Range(headerRangeAddress).Column).End(xlUp).Row
  If lastRow < ws.Range(dataStartCellAddress).Row Then Exit Sub

  Dim rng As Range: Set rng = ws.Range(headerRangeAddress).Resize(lastRow - ws.Range(headerRangeAddress).Row + 1, 5)
  Set lo = ws.ListObjects.Add(xlSrcRange, rng, , xlYes)
  lo.TableStyle = "TableStyleLight11"
End Sub

Private Sub WriteChangeLog(ByVal changes As Collection, ByVal dictPath As String)
  Dim ws As Worksheet: Set ws = GetOrCreateSheet(LOG_SHEET, False)
  Dim hasHeader As Boolean: hasHeader = (Trim$(SafeText(ws.Range("A1").Value2)) <> "")
  If Not hasHeader Then
    ws.Range("A1:G1").value = Array("Timestamp", "Sheet", "Cell", "Before", "After", "Scope", "Dictionary")
    ws.Range("A1:G1").Font.Bold = True
  End If

  Dim startRow As Long: startRow = ws.Cells(ws.Rows.count, 1).End(xlUp).Row + 1
  Dim arr() As Variant: ReDim arr(1 To changes.count, 1 To 7)
  Dim i As Long
  For i = 1 To changes.count
    Dim rec As Variant: rec = changes(i)
    arr(i, 1) = Now
    arr(i, 2) = rec(1)
    arr(i, 3) = rec(2)
    arr(i, 4) = rec(3)
    arr(i, 5) = rec(4)
    arr(i, 6) = rec(5)
    arr(i, 7) = dictPath
  Next
  ws.Range("A" & startRow).Resize(UBound(arr, 1), UBound(arr, 2)).value = arr
  ws.Columns("A:G").AutoFit
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

'========================
'   未保存CSVの注意喚起（★追加）
'========================
Private Sub WarnIfCsvUnsaved(ByVal csvPath As String)
  On Error Resume Next
  Dim wb As Workbook
  For Each wb In Application.Workbooks
    If StrComp(wb.fullName, csvPath, vbTextCompare) = 0 Then
      If Not wb.Saved Then
        MsgBox "辞書CSVが未保存です。保存してからプレビュー／反映してください。", vbExclamation
      End If
      Exit For
    End If
  Next
End Sub


