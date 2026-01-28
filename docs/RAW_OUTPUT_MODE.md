# TranslateGemma 生出力モード（テキスト翻訳）

## 目的
- AIの出力をプログラム側で検証/整形/再試行せず、そのままUIに表示する。
- テキスト翻訳プロンプトは TranslateGemma 形式（**2つの空行 → 原文**）に統一する。

## 仕様差分（旧→新）
- **出力後処理**: パース/整形/再試行/言語ガードのUI側補正を行わない。
- **UI表示**: 1つの出力枠に raw 表示（複数スタイル比較・解説表示は出さない）。
- **文字列保持**: 先頭/末尾空白、改行、`Translation:` 等のプレフィックスを保持。
- **エスケープ**: `\n` / `\t` のリテラルは変換せず、そのまま表示/コピー。
- **コピー**: 生テキストをそのままコピー（Excel貼り付け向け整形は行わない）。
- **戻し訳**: raw 結果を表示（正規化なし）。

## プロンプト（SSOT）
SIMPLE_PROMPT_TEMPLATE（コード側の固定テンプレート）:
```
You are a professional {SOURCE_LANG} ({SOURCE_CODE}) to {TARGET_LANG} ({TARGET_CODE}) translator. Your goal is to accurately convey the meaning and nuances of the original {SOURCE_LANG} text while adhering to {TARGET_LANG} grammar, vocabulary, and cultural sensitivities.
Produce only the {TARGET_LANG} translation, without any additional explanations or commentary. Please translate the following {SOURCE_LANG} text into {TARGET_LANG}:


{TEXT}
```
補足:
- `{SOURCE_CODE}` / `{TARGET_CODE}` は **`ja` / `en`** を使用（現行実装）。
- `{TEXT}` の直前に **空行2つ** が入ることが前提。

## リグレッション観点チェックリスト
- [ ] 先頭/末尾の空白が欠落せず表示/コピーされる
- [ ] 改行がそのまま保持される（`CRLF/LF` 混在含む）
- [ ] リテラルの `\n` / `\t` が変換されない
- [ ] 引用符/バッククォート/コードブロックが改変されない
- [ ] Markdownがレンダリングされず、文字列として表示される
- [ ] `Translation:` 等の接頭辞が除去されない
- [ ] コピー結果が生出力と一致する（Excel向け整形なし）
- [ ] 戻し訳の表示がrawである

