# Excel 日本語→英語 翻訳ツール

M365 Copilotを使用してExcelの選択範囲の日本語を英訳します。

## 使用方法

1. Excelで翻訳したい範囲を選択
2. `★run.bat` をダブルクリック
3. 初回のみM365 Copilotにログイン

## 必要環境

- Windows 10/11
- Microsoft Excel
- Microsoft Edge
- M365 Copilotへのアクセス権

## 制限事項

- 1回のバッチで最大300行まで翻訳可能
- 日本語を含むセルのみが翻訳対象

## トラブルシューティング

### Copilotにログインできない / セッションが切れた

1. `★run.bat` を実行
2. 開いたEdgeウィンドウでM365 Copilotに再ログイン
3. 再度翻訳を実行

### 「ポートが使用中」エラー

別のEdgeプロセスがポート9333を使用しています。

1. タスクマネージャーでEdgeを全て終了
2. 再度 `★run.bat` を実行

### 翻訳結果がExcelに反映されない

- Excelファイルが読み取り専用でないか確認
- 選択範囲が正しいか確認
- Copilotの応答が完了するまで待つ

### Edgeが起動しない

- Microsoft Edgeがインストールされているか確認
- `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` が存在するか確認

## バージョン: 20251126
