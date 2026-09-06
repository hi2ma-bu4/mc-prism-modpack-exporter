# mc-prism-modpack-exporter

Prism Launcher の Minecraft インスタンスから、再頒布可能な Modpack を生成するツールです。

Prism Launcher のインスタンスには、Mod の実体（JAR / ZIP）が直接配置されている場合があります。

本ツールでは、それらの Mod を配布元から再取得できる情報へ変換し、Mod の実体を Modpack に含めずに `modrinth.index.json` へ登録します。

これにより、Prism Launcher のインスタンスから、Mod の実体を含まない再頒布可能な Modpack を生成できます。

本ツールは Prism Launcher を主な対象としています。
Prism Launcher と同様のインスタンス構造や `.pw.toml` メタデータを使用する環境でも動作する可能性がありますが、動作は保証していません。

## Features

- Prism Launcher のインスタンスから Modpack を生成
- Prism Launcher の `.index/*.pw.toml` を利用して Mod の配布情報を解決
- CurseForge の Project ID / File ID による配布情報に対応
- Prism Launcher に設定された直接ダウンロードURLに対応
- 既存の Modrinth index の Mod 情報を維持
- Modpack に直接含まれている JAR / ZIP を外部ダウンロード形式へ変換
- Mod の SHA-1 / SHA-512 ハッシュを生成
- 自動解決できない Mod のための手動フォールバックに対応
- 生成した Modpack に Mod の実体を含めない
- Modrinth `.mrpack` 形式で出力

## How it works

概念的には、以下のように変換します。

```text
Prism Launcher instance
        │
        ├── mods/*.jar
        ├── mods/*.zip
        └── mods/.index/*.pw.toml
                │
                ▼
      Mod の配布情報を解決
                │
                ├── Prism metadata
                ├── CurseForge
                ├── 既存のModrinth index
                └── 手動フォールバック
                │
                ▼
         modrinth.index.json
                │
                ▼
          output.mrpack
```

例えば、インスタンス内に直接存在する Mod が

```text
mods/example-mod-1.0.0.jar
```

として配置されていた場合、その JAR 自体を Modpack に含めるのではなく、

```json
{
  "path": "mods/example-mod-1.0.0.jar",
  "hashes": {
    "sha1": "...",
    "sha512": "..."
  },
  "downloads": [
    "https://..."
  ],
  "fileSize": 123456,
  "env": {
    "client": "required",
    "server": "required"
  }
}
```

のような Modrinth index エントリとして登録します。

その後、元の JAR / ZIP は MRPack から除去されます。

## Mod の解決方法

Mod の配布元は、可能な限り既存のメタデータから自動的に解決されます。

基本的には以下の順で解決します。

1. Prism Launcher の `.pw.toml`
2. CurseForge の Project ID / File ID
3. Prism Launcher の直接ダウンロードURL
4. 既存の Modrinth index に登録されているダウンロードURL
5. `MANUAL_FALLBACKS` による手動指定

自動的に配布元を特定できない Mod が存在する場合、処理はエラーとして終了します。

これにより、配布元が不明な Mod を別バージョンのファイルなどに誤って置き換えることを防ぎます。

## Manual fallback

一部の Mod は、Prism Launcher のメタデータなどから配布元を自動的に特定できない場合があります。

その場合は、`build_mrpack.py` の `MANUAL_FALLBACKS` に対象 Mod の SHA-1 とダウンロードURLを指定できます。

デフォルトでは空になっています。

```python
MANUAL_FALLBACKS = {}
```

例えば、以下のように指定します。

```python
MANUAL_FALLBACKS = {
    "example-mod-1.0.0.jar": {
        "sha1": "0123456789abcdef0123456789abcdef01234567",
        "url": "https://example.com/example-mod-1.0.0.jar",
    },
}
```

`sha1` は、変換元インスタンスに存在する実際の Mod ファイルの SHA-1 と一致している必要があります。

SHA-1 が一致しない場合、そのフォールバックは使用されません。

### なぜ SHA-1 を指定するのか

ファイル名だけでフォールバック先を指定すると、同じファイル名の別バージョンを誤って使用する可能性があります。

そのため、

```text
ファイル名 + SHA-1
```

の両方を確認してから手動指定したURLを使用します。

手動フォールバックを追加する場合は、対象ファイルのハッシュとURLが正しいことを確認してください。

## Requirements

- Python 3.10 以降
- Prism Launcher
- 変換元の `.mrpack`
- 対応する CurseForge export ZIP
- 変換対象の Prism Launcher インスタンス

## Usage

```cmd
python build_mrpack.py <BASE.mrpack> <CURSEFORGE.zip> <OUTPUT.mrpack> [PRISM_INSTANCE_DIR]
```

### Example

```cmd
python build_mrpack.py example.mrpack curseforge-export.zip output.mrpack "C:\Games\PrismLauncher\instances\Example"
```

`PRISM_INSTANCE_DIR` を指定すると、そのインスタンスの

    minecraft/mods/.index/*.pw.toml

から Mod の配布情報を取得します。

## Output

生成された `.mrpack` には、変換対象となった Mod の JAR / ZIP を直接含めません。

代わりに `modrinth.index.json` にダウンロードURLとハッシュを登録します。

そのため、生成された Modpack を別のユーザーが利用する際には、Modrinth index に登録されたURLから各 Mod が取得されます。

## Notes

このツールは Prism Launcher のインスタンス構造を前提としています。

Mod 自体を再配布するものではなく、Modpack 内の Mod 実体を外部ダウンロード形式へ変換することを目的としています。

実際に生成・配布する Modpack については、各 Mod のライセンスおよび配布条件を確認してください。
