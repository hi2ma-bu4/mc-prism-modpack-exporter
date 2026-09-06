import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path


# ============================================================
# Manual fallback configuration
# ============================================================
#
# 自動解決できないModがある場合のみ、ここに手動で配布元を指定できます。
#
# 例:
#
# MANUAL_FALLBACKS = {
#     "example-mod.jar": {
#         "sha1": "0123456789abcdef0123456789abcdef01234567",
#         "url": "https://example.com/example-mod.jar",
#     },
# }
#
# sha1 は対象となる実ファイルのSHA-1と一致している必要があります。
# 不一致の場合はフォールバックを使用しません。
#
MANUAL_FALLBACKS = {}


# ============================================================
# Hash utilities
# ============================================================

def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def sha512_bytes(data: bytes) -> str:
    return hashlib.sha512(data).hexdigest()


# ============================================================
# Filename utilities
# ============================================================

def normalize_filename(filename: str) -> str:
    """
    Modのファイル名比較用に、英数字以外を除去して小文字化する。
    """
    return re.sub(r"[^a-z0-9]", "", filename.lower())


def is_mod_file(path: str) -> bool:
    """
    MRPack内の overrides/mods に存在するMod実体か判定する。
    """
    normalized = path.replace("\\", "/")

    if not normalized.startswith("overrides/mods/"):
        return False

    return normalized.lower().endswith((".jar", ".zip"))


def is_mod_index_file(path: str) -> bool:
    """
    MRPack index上のModファイルか判定する。
    """
    normalized = path.replace("\\", "/")

    if not normalized.startswith("mods/"):
        return False

    return normalized.lower().endswith((".jar", ".zip"))


# ============================================================
# Prism Launcher metadata
# ============================================================

def get_prism_metadata_dirs(instance_dir: Path):
    """
    Prism Launcher instance の .index ディレクトリ候補を返す。
    """
    candidates = []

    primary = instance_dir / "minecraft" / "mods" / ".index"

    if primary.is_dir():
        candidates.append(primary)

    return candidates


def parse_pw_toml(text: str):
    """
    Prism Launcher の .pw.toml から必要な項目だけを取得する。

    対応項目:
      filename
      project-id
      file-id
      hash
      hash-format
      name
      download.url
      download.mode
    """

    result = {
        "filename": None,
        "project_id": None,
        "file_id": None,
        "hash": None,
        "hash_format": None,
        "name": None,
        "download_url": None,
        "download_mode": None,
    }

    section = None

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        section_match = re.match(r"^\[([^\]]+)\]$", line)

        if section_match:
            section = section_match.group(1).strip()
            continue

        match = re.match(r'^([A-Za-z0-9_-]+)\s*=\s*"([^"]*)"$', line)

        if not match:
            continue

        key, value = match.groups()

        if section == "download":
            if key == "url":
                result["download_url"] = value
            elif key == "mode":
                result["download_mode"] = value

        elif section is None:
            if key == "filename":
                result["filename"] = value
            elif key == "project-id":
                result["project_id"] = value
            elif key == "file-id":
                result["file_id"] = value
            elif key == "hash":
                result["hash"] = value
            elif key == "hash-format":
                result["hash_format"] = value
            elif key == "name":
                result["name"] = value

    return result


def read_prism_metadata(instance_dir: Path):
    """
    Prism Launcher の .index/*.pw.toml を読み込む。
    """
    metadata = []

    for metadata_dir in get_prism_metadata_dirs(instance_dir):
        for path in sorted(metadata_dir.glob("*.pw.toml")):
            try:
                text = path.read_text(encoding="utf-8")
                entry = parse_pw_toml(text)

                if entry["filename"]:
                    entry["metadata_path"] = path
                    metadata.append(entry)

            except Exception as e:
                print(f"[WARN] Prism metadata read failed: {path}")
                print(f"       {e}")

    return metadata


def build_prism_indexes(metadata):
    """
    Prism metadataを複数のキーで検索できるようにする。
    """
    by_filename = {}
    by_normalized_filename = {}
    by_hash = {}

    for entry in metadata:
        filename = entry.get("filename")

        if filename:
            by_filename[filename.lower()] = entry
            by_normalized_filename[
                normalize_filename(filename)
            ] = entry

        hash_value = entry.get("hash")

        if hash_value:
            by_hash[hash_value.lower()] = entry

    return {
        "filename": by_filename,
        "normalized_filename": by_normalized_filename,
        "hash": by_hash,
    }


# ============================================================
# CurseForge export
# ============================================================

def read_curseforge_export(cf_zip_path: Path):
    """
    CurseForge export ZIPからmanifest.jsonとMod実体を取得する。
    """

    with zipfile.ZipFile(cf_zip_path, "r") as zf:
        manifest = json.loads(
            zf.read("manifest.json").decode("utf-8")
        )

        files = {}

        for info in zf.infolist():
            name = info.filename.replace("\\", "/")

            if not name.lower().endswith((".jar", ".zip")):
                continue

            data = zf.read(info)

            files[name] = {
                "filename": Path(name).name,
                "data": data,
                "sha1": sha1_bytes(data),
                "sha512": sha512_bytes(data),
            }

    return manifest, files


def build_cf_file_indexes(cf_files):
    """
    CurseForge export内のMod実体を検索するためのindex。
    """
    by_filename = {}
    by_normalized_filename = {}
    by_sha1 = {}
    by_sha512 = {}

    for path, entry in cf_files.items():
        filename = entry["filename"]

        by_filename[filename.lower()] = entry
        by_normalized_filename[
            normalize_filename(filename)
        ] = entry
        by_sha1[entry["sha1"].lower()] = entry
        by_sha512[entry["sha512"].lower()] = entry

    return {
        "filename": by_filename,
        "normalized_filename": by_normalized_filename,
        "sha1": by_sha1,
        "sha512": by_sha512,
    }


# ============================================================
# Modrinth index
# ============================================================

def read_mrpack_index(zf: zipfile.ZipFile):
    """
    元MRPackの modrinth.index.json を読み込む。
    """
    return json.loads(
        zf.read("modrinth.index.json").decode("utf-8")
    )


def build_mr_index_indexes(index):
    """
    Modrinth indexのModエントリを検索するためのindex。
    """
    by_sha1 = {}
    by_sha512 = {}
    by_filename = {}
    by_normalized_filename = {}

    for file_entry in index.get("files", []):
        path = file_entry.get("path", "")

        if not is_mod_index_file(path):
            continue

        hashes = file_entry.get("hashes", {})

        sha1 = hashes.get("sha1")
        sha512 = hashes.get("sha512")

        if sha1:
            by_sha1[sha1.lower()] = file_entry

        if sha512:
            by_sha512[sha512.lower()] = file_entry

        filename = Path(path).name

        by_filename[filename.lower()] = file_entry
        by_normalized_filename[
            normalize_filename(filename)
        ] = file_entry

    return {
        "sha1": by_sha1,
        "sha512": by_sha512,
        "filename": by_filename,
        "normalized_filename": by_normalized_filename,
    }


def find_existing_mr_entry(
    filename,
    sha1,
    sha512,
    mr_indexes,
):
    """
    既存MRPack indexから対象Modを検索する。
    """

    if sha1:
        entry = mr_indexes["sha1"].get(sha1.lower())

        if entry:
            return entry

    if sha512:
        entry = mr_indexes["sha512"].get(sha512.lower())

        if entry:
            return entry

    entry = mr_indexes["filename"].get(filename.lower())

    if entry:
        return entry

    entry = mr_indexes["normalized_filename"].get(
        normalize_filename(filename)
    )

    if entry:
        return entry

    return None


# ============================================================
# CurseForge source resolution
# ============================================================

def make_cf_download_url(project_id, file_id):
    """
    CurseForge File IDから公開ダウンロードURLを生成する。
    """
    return (
        "https://www.curseforge.com/api/v1/mods/"
        f"{project_id}/files/{file_id}/download"
    )


def build_cf_manifest_index(manifest):
    """
    CurseForge manifestのfilesを検索しやすい形にする。
    """
    by_project_file = {}

    for entry in manifest.get("files", []):
        project_id = str(entry.get("projectID"))
        file_id = str(entry.get("fileID"))

        if not project_id or not file_id:
            continue

        by_project_file[(project_id, file_id)] = entry

    return by_project_file


def find_cf_source(prism_entry, cf_manifest_index):
    """
    Prism metadataのproject-id / file-idから
    CurseForgeの配布情報を解決する。
    """

    project_id = prism_entry.get("project_id")
    file_id = prism_entry.get("file_id")

    if not project_id or not file_id:
        return None

    key = (str(project_id), str(file_id))

    if key not in cf_manifest_index:
        return None

    return {
        "url": make_cf_download_url(project_id, file_id),
        "project_id": str(project_id),
        "file_id": str(file_id),
    }


# ============================================================
# Manual fallback
# ============================================================

def find_manual_fallback(filename, sha1):
    """
    MANUAL_FALLBACKSから対象Modの手動配布情報を取得する。

    filenameだけではなくSHA-1も一致する場合のみ使用する。
    """

    fallback = MANUAL_FALLBACKS.get(filename)

    if fallback is None:
        fallback = MANUAL_FALLBACKS.get(
            filename.lower()
        )

    if fallback is None:
        return None

    expected_sha1 = str(
        fallback.get("sha1", "")
    ).lower()

    if not expected_sha1:
        print(
            f"[WARN] Manual fallback has no SHA-1: {filename}"
        )
        return None

    if expected_sha1 != sha1.lower():
        print(
            f"[WARN] Manual fallback SHA-1 mismatch: {filename}"
        )
        print(f"       expected: {expected_sha1}")
        print(f"       actual:   {sha1}")
        return None

    url = fallback.get("url")

    if not url:
        print(
            f"[WARN] Manual fallback has no URL: {filename}"
        )
        return None

    return {
        "url": url,
    }


# ============================================================
# Existing Mod entry resolution
# ============================================================

def process_mod_entry(
    entry,
    prism_indexes,
    cf_manifest_index,
):
    """
    既存MRPack indexのModエントリについて、
    Prism / CurseForge情報を利用して配布URLを解決する。
    """

    path = entry.get("path", "")
    filename = Path(path).name

    hashes = entry.get("hashes", {})

    sha1 = hashes.get("sha1")
    sha512 = hashes.get("sha512")

    prism_entry = None

    if sha1:
        prism_entry = prism_indexes["hash"].get(
            sha1.lower()
        )

    if prism_entry is None:
        prism_entry = prism_indexes["filename"].get(
            filename.lower()
        )

    if prism_entry is None:
        prism_entry = prism_indexes["normalized_filename"].get(
            normalize_filename(filename)
        )

    if prism_entry:
        cf_source = find_cf_source(
            prism_entry,
            cf_manifest_index,
        )

        if cf_source:
            new_entry = dict(entry)

            new_entry["downloads"] = [
                cf_source["url"]
            ]

            return new_entry

        prism_url = prism_entry.get("download_url")

        if prism_url:
            new_entry = dict(entry)

            new_entry["downloads"] = [
                prism_url
            ]

            return new_entry

    # 既存URLを維持
    if entry.get("downloads"):
        return dict(entry)

    return None


# ============================================================
# Embedded Mod handling
# ============================================================

def build_embedded_mod_entry(
    filename,
    data,
    prism_indexes,
    cf_manifest_index,
    mr_indexes,
):
    """
    MRPackに実体として同梱されているModを
    外部ダウンロード形式のindex entryへ変換する。
    """

    sha1 = sha1_bytes(data)
    sha512 = sha512_bytes(data)
    file_size = len(data)

    # --------------------------------------------------------
    # 既存indexに同一Modが存在する場合
    # --------------------------------------------------------

    existing = find_existing_mr_entry(
        filename,
        sha1,
        sha512,
        mr_indexes,
    )

    if existing:
        new_entry = dict(existing)

        new_entry["path"] = f"mods/{filename}"
        new_entry["hashes"] = {
            "sha1": sha1,
            "sha512": sha512,
        }

        new_entry["fileSize"] = file_size

        return new_entry

    # --------------------------------------------------------
    # Prism metadata
    # --------------------------------------------------------

    prism_entry = None

    prism_entry = prism_indexes["hash"].get(
        sha1.lower()
    )

    if prism_entry is None:
        prism_entry = prism_indexes["filename"].get(
            filename.lower()
        )

    if prism_entry is None:
        prism_entry = prism_indexes["normalized_filename"].get(
            normalize_filename(filename)
        )

    download_url = None

    if prism_entry:
        # ----------------------------------------------------
        # CurseForge
        # ----------------------------------------------------

        cf_source = find_cf_source(
            prism_entry,
            cf_manifest_index,
        )

        if cf_source:
            download_url = cf_source["url"]

        # ----------------------------------------------------
        # Prism direct URL
        # ----------------------------------------------------

        if download_url is None:
            prism_url = prism_entry.get("download_url")

            if prism_url:
                download_url = prism_url

    # --------------------------------------------------------
    # Manual fallback
    # --------------------------------------------------------

    if download_url is None:
        fallback = find_manual_fallback(
            filename,
            sha1,
        )

        if fallback:
            download_url = fallback["url"]

    # --------------------------------------------------------
    # Could not resolve
    # --------------------------------------------------------

    if download_url is None:
        return None

    return {
        "path": f"mods/{filename}",
        "hashes": {
            "sha1": sha1,
            "sha512": sha512,
        },
        "env": {
            "client": "required",
            "server": "required",
        },
        "downloads": [
            download_url
        ],
        "fileSize": file_size,
    }


# ============================================================
# Main
# ============================================================

def main():
    if len(sys.argv) < 4:
        print(
            "Usage: "
            "py build_mrpack.py "
            "BASE.mrpack CF.zip OUTPUT.mrpack "
            "[PRISM_INSTANCE_DIR]"
        )
        sys.exit(1)

    base_mrpack_path = Path(sys.argv[1])
    cf_zip_path = Path(sys.argv[2])
    output_path = Path(sys.argv[3])

    prism_instance_dir = (
        Path(sys.argv[4])
        if len(sys.argv) >= 5
        else None
    )

    # ========================================================
    # Prism metadata
    # ========================================================

    prism_metadata = []

    if prism_instance_dir:
        prism_metadata = read_prism_metadata(
            prism_instance_dir
        )

    prism_indexes = build_prism_indexes(
        prism_metadata
    )

    print("=== 入力解析 ===")
    print(f"Prism metadata: {len(prism_metadata)}")

    # ========================================================
    # CurseForge export
    # ========================================================

    cf_manifest, cf_files = read_curseforge_export(
        cf_zip_path
    )

    cf_manifest_index = build_cf_manifest_index(
        cf_manifest
    )

    cf_indexes = build_cf_file_indexes(
        cf_files
    )

    print(f"CurseForge export: {len(cf_files)}")

    # ========================================================
    # Open original MRPack
    # ========================================================

    with zipfile.ZipFile(
        base_mrpack_path,
        "r",
    ) as base_zf:

        index = read_mrpack_index(base_zf)

        original_files = base_zf.namelist()

        mr_indexes = build_mr_index_indexes(
            index
        )

        original_mod_entries = [
            entry
            for entry in index.get("files", [])
            if is_mod_index_file(
                entry.get("path", "")
            )
        ]

        embedded_mod_paths = [
            path
            for path in original_files
            if is_mod_file(path)
        ]

        print(
            f"MRPack index Mod: "
            f"{len(original_mod_entries)}"
        )

        print(
            f"MRPack embedded Mod: "
            f"{len(embedded_mod_paths)}"
        )

        # ====================================================
        # Existing index Mod processing
        # ====================================================

        new_index_files = []

        unresolved_index_mods = []

        for entry in index.get("files", []):
            if not is_mod_index_file(
                entry.get("path", "")
            ):
                new_index_files.append(entry)
                continue

            processed = process_mod_entry(
                entry,
                prism_indexes,
                cf_manifest_index,
            )

            if processed is None:
                unresolved_index_mods.append(
                    Path(
                        entry.get("path", "")
                    ).name
                )
            else:
                new_index_files.append(
                    processed
                )

        if unresolved_index_mods:
            print()
            print(
                "=== index Mod 未解決 ==="
            )

            for filename in unresolved_index_mods:
                print(f"  {filename}")

            print()
            print(
                "自動解決できないModがあります。"
            )
            print(
                "Prism metadata、既存URL、または"
                "MANUAL_FALLBACKSを確認してください。"
            )

            sys.exit(1)

        # ====================================================
        # Embedded Mod processing
        # ====================================================

        embedded_entries = []
        unresolved_embedded_mods = []

        for path in embedded_mod_paths:
            filename = Path(path).name
            data = base_zf.read(path)

            entry = build_embedded_mod_entry(
                filename,
                data,
                prism_indexes,
                cf_manifest_index,
                mr_indexes,
            )

            if entry is None:
                unresolved_embedded_mods.append(
                    filename
                )
                continue

            embedded_entries.append(entry)

        print()
        print("=== 同梱Mod移行結果 ===")
        print(
            f"同梱Mod実体: "
            f"{len(embedded_mod_paths)}"
        )
        print(
            f"indexへ追加: "
            f"{len(embedded_entries)}"
        )
        print(
            f"未解決: "
            f"{len(unresolved_embedded_mods)}"
        )

        if unresolved_embedded_mods:
            print()

            for filename in unresolved_embedded_mods:
                print(f"  {filename}")

            print()
            print(
                "自動解決できない同梱Modがあります。"
            )
            print(
                "必要に応じてMANUAL_FALLBACKSへ"
                "SHA-1とダウンロードURLを追加してください。"
            )

            sys.exit(1)

        # ====================================================
        # Append embedded entries
        # ====================================================

        new_index_files.extend(
            embedded_entries
        )

        index["files"] = new_index_files

        # ====================================================
        # Validation
        # ====================================================

        final_mod_entries = [
            entry
            for entry in index.get("files", [])
            if is_mod_index_file(
                entry.get("path", "")
            )
        ]

        expected_mod_count = (
            len(original_mod_entries)
            + len(embedded_mod_paths)
        )

        print()
        print("=== 最終検証 ===")
        print(
            f"index上Mod: "
            f"{len(final_mod_entries)}"
        )
        print(
            f"期待値: "
            f"{expected_mod_count}"
        )

        if len(final_mod_entries) != expected_mod_count:
            print(
                "[ERROR] index上のMod数が期待値と一致しません。"
            )
            sys.exit(1)

        # ====================================================
        # Write output MRPack
        # ====================================================

        temp_output = output_path.with_suffix(
            output_path.suffix + ".tmp"
        )

        if temp_output.exists():
            temp_output.unlink()

        with zipfile.ZipFile(
            temp_output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as out_zf:

            for item in base_zf.infolist():
                path = item.filename.replace(
                    "\\",
                    "/",
                )

                # ------------------------------------------------
                # modrinth.index.json
                # ------------------------------------------------

                if path == "modrinth.index.json":
                    out_zf.writestr(
                        item,
                        json.dumps(
                            index,
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                    continue

                # ------------------------------------------------
                # Remove embedded mods
                # ------------------------------------------------

                if is_mod_file(path):
                    continue

                out_zf.writestr(
                    item,
                    base_zf.read(item),
                )

        temp_output.replace(output_path)

    # ========================================================
    # Final verification
    # ========================================================

    with zipfile.ZipFile(
        output_path,
        "r",
    ) as zf:

        output_index = json.loads(
            zf.read(
                "modrinth.index.json"
            ).decode("utf-8")
        )

        remaining_mod_files = [
            path
            for path in zf.namelist()
            if is_mod_file(path)
        ]

        output_mod_entries = [
            entry
            for entry in output_index.get("files", [])
            if is_mod_index_file(
                entry.get("path", "")
            )
        ]

    print()
    print("=== 結果 ===")
    print(
        f"最終index Mod数: "
        f"{len(output_mod_entries)}"
    )
    print(
        f"残存 overrides/mods/*.jar/.zip: "
        f"{len(remaining_mod_files)}"
    )

    if remaining_mod_files:
        print(
            "[ERROR] 同梱Modが残っています。"
        )

        for path in remaining_mod_files:
            print(f"  {path}")

        sys.exit(1)

    if len(output_mod_entries) != expected_mod_count:
        print(
            "[ERROR] 最終index Mod数が期待値と一致しません。"
        )
        sys.exit(1)

    print(
        f"[OK] overrides/mods/*.jar/.zip: "
        f"{len(remaining_mod_files)}"
    )

    print(
        f"[OK] index上Mod: "
        f"{len(output_mod_entries)}"
    )

    print(
        f"[OK] "
        f"{len(original_mod_entries)} + "
        f"{len(embedded_mod_paths)} = "
        f"{expected_mod_count}"
    )

    print(
        f"[OK] MRPack generated: "
        f"{output_path}"
    )


if __name__ == "__main__":
    main()
