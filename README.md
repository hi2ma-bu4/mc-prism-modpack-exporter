# mc-prism-modpack-exporter

Prism Launcher の Minecraft インスタンスから、再頒布可能な Modpack を生成するツールです。

Prism Launcher の `.minecraft` 環境には、Mod の実体（JAR/ZIP）が直接配置されている場合があります。
本ツールでは、それらの Mod を配布元から再取得できる情報へ変換し、Mod の実体を含まない Modpack を生成します。

これにより、他の Prism Launcher ユーザーへ再頒布しやすい Modpack を作成できます。

## Features

- Prism Launcher のインスタンスから Modpack を生成
- Prism Launcher の `.index/*.pw.toml` を利用して Mod の配布情報を解決
- CurseForge の Project ID / File ID による配布情報に対応
- 既存の Modrinth index の Mod 情報を維持
- Modpack に直接含まれている JAR / ZIP を外部ダウンロード形式へ変換
- Mod の SHA-1 / SHA-512 ハッシュを生成
- 生成した Modpack に Mod の実体を含めない
- Modrinth `.mrpack` 形式で出力

## How it works

概念的には、以下のように変換します。

    Prism Launcher instance
            │
            ├── mods/*.jar
            ├── mods/*.zip
            └── mods/.index/*.pw.toml
                    │
                    ▼
          Mod の配布情報を解決
                    │
                    ▼
             modrinth.index.json
                    │
                    ▼
              output.mrpack

例えば、インスタンス内に直接存在する Mod が

    mods/example-mod-1.0.0.jar

として配置されていた場合、その JAR 自体を Modpack に含めるのではなく、

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

のような Modrinth index エントリとして登録します。

その後、元の JAR / ZIP は MRPack から除去されます。

## Requirements

- Python 3.10 以降
- Prism Launcher
- 変換元の `.mrpack`
- 対応する CurseForge export ZIP
- Prism Launcher の対象インスタンス

## Usage

```text
python build_mrpack.py <BASE.mrpack> <CURSEFORGE.zip> <OUTPUT.mrpack> [PRISM_INSTANCE_DIR]
