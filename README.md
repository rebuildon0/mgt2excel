# MGT2Excel

midas iGen の MGT（モデル）/ ANL（解析結果テキスト）から、断面算定に使いやすい Excel を生成するツール。

**🌐 Web 版（インストール不要）: https://rebuildon0.github.io/mgt2excel/**

- 分割された直線要素を「一本部材」に自動統合し、**通し長さ＝座屈長さ**として出力
- 荷重ケースごとに N・Qy・Qz・Mt・My・Mz の max/min を部材単位で集計
- 単位は kN・kN·m・mm に自動換算（tonf / kgf / kN / N × mm / cm / m に対応）
- ファイルは**ブラウザ内だけで処理**され、サーバーに送信されない（Pyodide = ブラウザ内 Python）

## ドキュメント

- [使い方（スクリーンショット付き）](https://rebuildon0.github.io/mgt2excel/manual.html)
- [部材統合の判定ロジック（技術説明書）](https://rebuildon0.github.io/mgt2excel/logic.html)

## CLI / ローカル実行（上級者向け）

変換エンジンの実体は [mgt2excel.py](mgt2excel.py)。Web 版はこれを Pyodide 上でそのまま実行している。
数万要素の大きなモデルはローカル実行のほうが高速。

```powershell
pip install openpyxl
py -3 mgt2excel.py model.mgt [model.anl] [-o out.xlsx]
        [--no-support-split] [--no-release-split] [--no-unit-convert]
```

引数なしで実行すると tkinter の GUI が起動する。
Windows 用単体 exe は PyInstaller でビルドできる:

```powershell
py -3 -m PyInstaller --onefile --noconsole --name MGT2Excel mgt2excel.py
```

## テスト

```powershell
py -3 -m unittest test_mgt2excel -v
```

## リポジトリ構成

| ファイル | 役割 |
|---|---|
| `index.html` / `worker.js` | Web アプリ（GitHub Pages で配信） |
| `mgt2excel.py` | 変換エンジン本体（Web/CLI/GUI 共通） |
| `test_mgt2excel.py` | ユニットテスト |
| `manual.html` / `logic.html` | 使い方・判定ロジックの説明書 |

## ライセンス / 免責

社内業務効率化のために作成したツールです。出力値の妥当性は必ず設計者が確認してください。
