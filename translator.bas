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
Private Const CELL_STATUS  As String = "B15"

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

#If VBA7 Then
Private Declare PtrSafe Function MultiByteToWideChar Lib "kernel32" _
  (ByVal CodePage As Long, ByVal dwFlags As Long, ByVal lpMultiByteStr As LongPtr, _
   ByVal cbMultiByte As Long, ByVal lpWideCharStr As LongPtr, ByVal cchWideChar As Long) As Long
#Else
Private Declare Function MultiByteToWideChar Lib "kernel32" _
  (ByVal CodePage As Long, ByVal dwFlags As Long, ByVal lpMultiByteStr As Long, _
   ByVal cbMultiByte As Long, ByVal lpWideCharStr As Long, ByVal cchWideChar As Long) As Long
#End If

Private Const CP_UTF8 As Long = 65001
Private Const CP_SHIFT_JIS As Long = 932
Private Const CP_ACP As Long = 0

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
    .value = LabelWithIcon("globe", "ECM Translator")
    .Font.Bold = True
    .Font.Size = 18
    .Font.Color = COLOR_TEXT
    On Error Resume Next
    .Font.Name = IIf(USE_EMOJI, "Segoe UI Emoji", UI_FONT)
    If .Font.Name <> "Segoe UI Emoji" And USE_EMOJI Then .Font.Name = "Segoe UI Symbol"
    If .Font.Name <> "Segoe UI Emoji" And .Font.Name <> "Segoe UI Symbol" Then .Font.Name = ALT_FONT
    On Error GoTo 0
  End With
  ws.Range("A1:F1").Interior.Color = COLOR_PRIMARY_LIGHT

  ws.Range("A2").value = "翻訳対象のブックと辞書CSVを指定し、「翻訳」を実行してください。"
  ws.Range("A2:F2").Merge
  ws.Range("A2:F2").Interior.Color = COLOR_PRIMARY_LIGHT
  ws.Range("A2").Font.Color = COLOR_TEXT
  ws.Range("A2").Font.Size = 11

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
  ws.Range("A14").value = "ステータス"
  ws.Range("A14").Font.Bold = True
  ws.Range("B15:F15").Merge
  With ws.Range(CELL_STATUS)
    .value = "Ready"
    .HorizontalAlignment = xlLeft
    .VerticalAlignment = xlTop
    .WrapText = True
  End With

  DeleteButtons ws, "btnECM_*"
  AddButton ws, "btnECM_BrowseWb", LabelWithIcon("folder", "ターゲット選択"), ws.Range("B6"), 220, "ECM_BrowseWorkbook", True, "翻訳先となるExcelブックを選択します。"
  AddButton ws, "btnECM_BrowseCsv", LabelWithIcon("index", "辞書CSV選択"), ws.Range("B10"), 220, "ECM_BrowseCSV", True, "翻訳辞書となるCSVファイルを選択します。"
  AddButton ws, "btnECM_Apply", LabelWithIcon("check", "翻訳"), ws.Range("B13"), 280, "ECM_ApplyTranslations", True, "辞書を使ってターゲットブックを翻訳します。"

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
    .Rows(14).RowHeight = 20
    .Rows(15).RowHeight = 30
  End With

  Application.ScreenUpdating = True
  Application.DisplayAlerts = True

  MsgBox "翻訳パネルを準備しました。ターゲットブックと辞書CSVを確認してから「翻訳」を実行してください。", vbInformation
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
  Dim errMsg As String: errMsg = "翻訳中にエラーが発生しました: " & Err.Description
  MsgBox errMsg, vbExclamation
  SetStatus errMsg

CleanExit:
  Application.EnableEvents = True
  Application.Calculation = oldCalc
  Application.ScreenUpdating = True
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

Private Sub ReopenDictionaryWorkbook(ByVal csvPath As String)
  Dim cleaned As String: cleaned = CleanPath(csvPath)
  If Len(cleaned) = 0 Then Exit Sub
  Dim oldAlerts As Boolean
  oldAlerts = Application.DisplayAlerts
  Application.DisplayAlerts = False
  On Error Resume Next
  Application.Workbooks.Open Filename:=cleaned, UpdateLinks:=False, ReadOnly:=False
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
    If LCase$(CleanPath(wb.FullName)) = LCase$(cleaned) Then
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

  Set probe = Application.Workbooks.Open(Filename:=cleaned, UpdateLinks:=False, ReadOnly:=False)
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
  Set wb = Application.Workbooks.Open(Filename:=path, ReadOnly:=False)
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
    total = textRng.Cells.count
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
          Set entry = idx.Item(key)
          If CStr(targetCell.Value2) <> CStr(entry.Item("target")) Then
            targetRange.Value2 = entry.Item("target")
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
        Set entry = idx.Item(key)
        Dim tgt As String: tgt = CStr(entry.Item("target"))
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
    g_lastCsvError = "read text throw " & Err.Number & ": " & Err.Description
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
  g_lastCsvError = stageInfo & "parse error " & Err.Number & ": " & Err.Description
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
    k = KeyFor(CStr(entry.Item("source")))
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
  On Error Resume Next
  ThisWorkbook.Worksheets(HELPER_SHEET).Range(CELL_STATUS).value = msg
  On Error GoTo 0
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

