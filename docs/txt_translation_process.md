# TXT ファイル翻訳フロー

`yakulingo/processors/txt_processor.py` の `TxtProcessor` がプレーンテキスト翻訳を担当します。主要なステップを実装箇所とあわせてまとめます。

## 1. ファイル情報取得 (`get_file_info`)
- UTF-8 で読み込み、空行（`"\n\n"`）で段落分割。
- 空でない段落のみカウントし、`FileInfo.page_count` に反映。
- 2 段落以上ある場合は `SectionDetail` を段落単位で生成して UI に渡します。

## 2. ブロック抽出 (`extract_text_blocks`)
- 段落を走査し、`MAX_CHARS_PER_BLOCK`（3,000 文字）超の段落は `_split_into_chunks` で文区切りを優先して分割。
- チャンクごとに `TextBlock` を生成し、ID を `para_<段落番号>_chunk_<チャンク番号>` として付与。
- 短い段落はチャンク化せず `para_<段落番号>` の ID を割り当て。
- `should_translate`（空白・数字のみを除外）に合格したテキストだけを翻訳対象として yield します。

## 3. チャンク分割ロジック (`_split_into_chunks`)
- 句点・感嘆符・改行後で正規表現スプリットし、区切り文字を前方に残して自然な塊を形成。
- それでも 3,000 文字を超える文は強制的に分割し、末尾のチャンクは余りを保持。

## 4. 翻訳適用 (`apply_translations`)
- 原文を再び段落分割し、対応する翻訳結果を `translations` のブロック ID で参照。
- チャンク化された段落は `_split_into_chunks` で同じ分割を行い、欠けているチャンクは原文を保持したまま順に連結。
- チャンク化されなかった段落は `para_<段落番号>` をキーに置き換え、未翻訳なら原文を残します。
- 結果を空行区切りで連結し、UTF-8 で出力します。

## 5. バイリンガル出力 (`create_bilingual_document`)
- 原文・訳文をそれぞれ段落分割し、`zip_longest` で並べて `【原文】...【訳文】...` の順で交互に配置。
- 段落間は 40 本の横線で区切ります。

## 6. 用語集 CSV (`export_glossary_csv`)
- 翻訳結果 `translations` と元テキスト `original_texts` を突合し、`原文,訳文` の列を UTF-8 BOM 付きで CSV 出力します。

## 確認観点
- 段落分割は空行が基準のため、単一改行のみの文章は同一段落として扱われます。
- チャンク化の再現性を保つため、`apply_translations` でも同じ `_split_into_chunks` を使用しています。
- 翻訳が返ってこなかったチャンクは原文保持で復元されるため、欠落によるテキスト消失は発生しません。
