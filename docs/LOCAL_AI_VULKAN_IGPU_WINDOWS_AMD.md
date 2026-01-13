# Windows (x64) + Ryzen 5 PRO 6650U 向け Vulkan(iGPU) 最小手順

この手順は、**Vulkan(iGPU) に実際にオフロードできていること**を確認し、**CPU-only との差が見える測り方**で比較するための最短ルートです。

## 前提
- Vulkan 版の `llama.cpp` バイナリが配置されていること（例: `local_ai/llama_cpp/vulkan/`）。
- モデルは同じものを使う（例: `local_ai/models/HY-MT1.5-1.8B-Q4_K_M.gguf`）。

## 1) Vulkan デバイスの確認
```powershell
cd local_ai/llama_cpp/vulkan
.\llama-cli.exe --list-devices
```
`Vulkan0: ... AMD Radeon ...` の表示が出れば iGPU が認識されています。

## 2) Vulkan(iGPU) を強制して実行
`--device` と `-ngl` を**明示**します（auto のままだと 0 層になる場合があります）。
```powershell
  cd local_ai/llama_cpp/vulkan
  .\llama-cli.exe `
  -m "..\\..\\models\\HY-MT1.5-1.8B-Q4_K_M.gguf" `
  --device Vulkan0 `
  -ngl all `
  -t 6 `
  -c 4096 `
  -b 2048 -ub 512 `
  -n 128 `
  -p "日本語で自己紹介して。"
```
`ggml_vulkan` の GPU 検出ログが出ない場合は Vulkan バイナリや DLL の整合性を確認してください。

## 3) CPU-only と Vulkan(iGPU) を同条件で比較
`-pg <pp,tg>` で **pp と tg を分離**して比較します。iGPU は pp が伸びやすく、tg は差が小さく見えることがあります。

### CPU-only
```powershell
  cd local_ai/llama_cpp/vulkan
  .\llama-bench.exe `
  -m "..\\..\\models\\HY-MT1.5-1.8B-Q4_K_M.gguf" `
  --device none `
  -ngl 0 `
  -pg 2048,256 `
  -b 2048 -ub 512 `
  -fa 0 `
  -r 3
```

### Vulkan(iGPU)
```powershell
  cd local_ai/llama_cpp/vulkan
  .\llama-bench.exe `
  -m "..\\..\\models\\HY-MT1.5-1.8B-Q4_K_M.gguf" `
  --device Vulkan0 `
  -ngl all `
  -pg 2048,256 `
  -b 2048 -ub 512 `
  -fa 0 `
  -r 3
```

### スクリプトで一括比較（任意）
同じ条件で CPU-only と Vulkan(iGPU) を**1コマンドで実行**し、pp/tg 行と条件を保存できます。
CPU-only は `--device none -ngl 0` が固定で使われます。

```powershell
# リポジトリルートで実行
  uv run python tools\bench_llama_bench_compare.py `
    --server-dir local_ai\llama_cpp `
    --model-path local_ai\models\HY-MT1.5-1.8B-Q4_K_M.gguf `
    --pg 2048,256 -r 3 `
    --device Vulkan0 --n-gpu-layers all `
    --extra-args -b 2048 -ub 512 -fa 0 `
  --format markdown `
  --out .tmp\llama_bench_compare.md
```

詳細は `docs/PERFORMANCE_LOCAL_AI.md` を参照してください。

## 4) 6650U (UMA) の注意点
- **メモリ帯域がボトルネック**になりやすく、tg が伸びにくいことがある。
- **pp（prefill）** は伸びやすいので、比較は `-pg` を使って分離する。
- **デュアルチャネル**構成や電源設定で結果が大きく変わることがある。

## 参考
- ベンチ詳細: `docs/PERFORMANCE_LOCAL_AI.md`
