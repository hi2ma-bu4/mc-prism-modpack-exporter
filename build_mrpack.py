import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def sha512_bytes(data: bytes) -> str:
    return hashlib.sha512(data).hexdigest()


def normalize_filename(name: str) -> str:
    name = Path(name).name.lower()

    name = name.replace("%2b", "+")

    if name.endswith(".jar"):
        name = name[:-4]
    elif name.endswith(".zip"):
        name = name[:-4]

    return re.sub(r"[^a-z0-9]+", "", name)


def normalize_mod_name(name: str) -> str:
    name = Path(name).stem.lower()
    return re.sub(r"[^a-z0-9]+", "", name)


def is_mod_file(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()

    if not normalized.startswith("overrides/mods/"):
        return False

    return (
        normalized.endswith(".jar")
        or normalized.endswith(".zip")
    )


def is_mod_index_file(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()

    if not normalized.startswith("mods/"):
        return False

    return (
        normalized.endswith(".jar")
        or normalized.endswith(".zip")
    )


def get_prism_metadata_dirs(instance_dir: Path):
    """
    Prism Launcher instance の .index ディレクトリ候補を返す。

    通常は指定された instance の .index を使用する。

    ただし、

        1.20.1 snowsFactoryPack base

    のように末尾が " base" の場合、

        1.20.1 snowsFactoryPack

    もフォールバック候補として使用する。
    """

    candidates = []

    primary = (
        instance_dir
        / "minecraft"
        / "mods"
        / ".index"
    )

    if primary.is_dir():
        candidates.append(primary)

    name = instance_dir.name

    if name.endswith(" base"):
        fallback_instance = (
            instance_dir.parent
            / name[:-5]
        )

        fallback_index = (
            fallback_instance
            / "minecraft"
            / "mods"
            / ".index"
        )

        if (
            fallback_index.is_dir()
            and fallback_index != primary
        ):
            candidates.append(fallback_index)

    return candidates


def read_prism_metadata(instance_dir: Path):
    """
    Prism Launcher instance の

        minecraft/mods/.index/*.pw.toml

    を読む。
    """

    index_dirs = get_prism_metadata_dirs(
        instance_dir
    )

    if not index_dirs:
        raise RuntimeError(
            "Prism .index not found: "
            f"{instance_dir / 'minecraft' / 'mods' / '.index'}"
        )

    result_by_filename = {}

    for index_dir in index_dirs:
        for path in sorted(
            index_dir.glob("*.pw.toml")
        ):
            text = path.read_text(
                encoding="utf-8"
            )

            filename_match = re.search(
                r"(?m)^filename\s*=\s*['\"]([^'\"]+)['\"]",
                text,
            )

            if not filename_match:
                continue

            filename = filename_match.group(1)

            project_match = re.search(
                r"(?m)^project-id\s*=\s*(\d+)",
                text,
            )

            file_match = re.search(
                r"(?m)^file-id\s*=\s*(\d+)",
                text,
            )

            hash_match = re.search(
                r"(?m)^hash\s*=\s*['\"]([^'\"]+)['\"]",
                text,
            )

            hash_format_match = re.search(
                r"(?m)^hash-format\s*=\s*['\"]([^'\"]+)['\"]",
                text,
            )

            name_match = re.search(
                r"(?m)^name\s*=\s*['\"]([^'\"]*)['\"]",
                text,
            )

            download_url_match = re.search(
                r"(?ms)^\[download\]\s*.*?"
                r"^\s*url\s*=\s*['\"]([^'\"]*)['\"]",
                text,
            )

            download_mode_match = re.search(
                r"(?ms)^\[download\]\s*.*?"
                r"^\s*mode\s*=\s*['\"]([^'\"]*)['\"]",
                text,
            )

            key = filename.lower()

            if key in result_by_filename:
                continue

            result_by_filename[key] = {
                "path": path,
                "filename": filename,
                "name": (
                    name_match.group(1)
                    if name_match
                    else ""
                ),
                "project_id": (
                    int(project_match.group(1))
                    if project_match
                    else None
                ),
                "file_id": (
                    int(file_match.group(1))
                    if file_match
                    else None
                ),
                "hash": (
                    hash_match.group(1)
                    if hash_match
                    else None
                ),
                "hash_format": (
                    hash_format_match.group(1)
                    if hash_format_match
                    else None
                ),
                "download": (
                    download_url_match.group(1)
                    if download_url_match
                    else None
                ),
                "download_mode": (
                    download_mode_match.group(1)
                    if download_mode_match
                    else None
                ),
            }

    return list(
        result_by_filename.values()
    )


def build_prism_indexes(metadata):
    by_filename = {}
    by_normalized_filename = {}
    by_hash = {}

    for entry in metadata:
        filename = entry["filename"]

        by_filename.setdefault(
            filename.lower(),
            [],
        ).append(entry)

        normalized = normalize_filename(filename)

        by_normalized_filename.setdefault(
            normalized,
            [],
        ).append(entry)

        if entry["hash"]:
            by_hash.setdefault(
                entry["hash"].lower(),
                [],
            ).append(entry)

    return {
        "filename": by_filename,
        "normalized_filename": by_normalized_filename,
        "hash": by_hash,
    }


def find_prism_metadata(
    filename,
    indexes,
    sha1=None,
    sha512=None,
):
    """
    Prism metadataを探す。

    優先順位:

        1. SHA1
        2. SHA512
        3. filename完全一致
        4. filename正規化一致
    """

    if sha1:
        for entry in indexes["hash"].get(
            sha1.lower(),
            [],
        ):
            if (
                entry["hash_format"]
                and entry["hash_format"].lower()
                == "sha1"
            ):
                return entry, "SHA1"

    if sha512:
        for entry in indexes["hash"].get(
            sha512.lower(),
            [],
        ):
            if (
                entry["hash_format"]
                and entry["hash_format"].lower()
                == "sha512"
            ):
                return entry, "SHA512"

    candidates = indexes["filename"].get(
        filename.lower(),
        [],
    )

    if len(candidates) == 1:
        return candidates[0], "filename"

    normalized = normalize_filename(filename)

    candidates = indexes[
        "normalized_filename"
    ].get(
        normalized,
        [],
    )

    if len(candidates) == 1:
        return candidates[0], "normalized filename"

    return None, None


def read_zip_files(zip_path: Path):
    files = []

    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue

            name = info.filename
            filename = Path(name).name

            if not (
                filename.lower().endswith(".jar")
                or filename.lower().endswith(".zip")
            ):
                continue

            data = z.read(info)

            files.append({
                "zip_name": name,
                "filename": filename,
                "data": data,
                "sha1": sha1_bytes(data),
                "sha512": sha512_bytes(data),
            })

    return files


def build_file_indexes(files):
    by_filename = {}
    by_normalized = {}
    by_sha1 = {}
    by_sha512 = {}

    for file in files:
        filename = file["filename"]

        by_filename.setdefault(
            filename.lower(),
            [],
        ).append(file)

        by_normalized.setdefault(
            normalize_filename(filename),
            [],
        ).append(file)

        by_sha1.setdefault(
            file["sha1"].lower(),
            [],
        ).append(file)

        by_sha512.setdefault(
            file["sha512"].lower(),
            [],
        ).append(file)

    return {
        "filename": by_filename,
        "normalized": by_normalized,
        "sha1": by_sha1,
        "sha512": by_sha512,
    }


def find_file(
    filename,
    indexes,
    sha1=None,
    sha512=None,
):
    if sha1:
        candidates = indexes["sha1"].get(
            sha1.lower(),
            [],
        )

        if len(candidates) == 1:
            return candidates[0], "SHA1"

    if sha512:
        candidates = indexes["sha512"].get(
            sha512.lower(),
            [],
        )

        if len(candidates) == 1:
            return candidates[0], "SHA512"

    candidates = indexes["filename"].get(
        filename.lower(),
        [],
    )

    if len(candidates) == 1:
        return candidates[0], "filename"

    normalized = normalize_filename(filename)

    candidates = indexes["normalized"].get(
        normalized,
        [],
    )

    if len(candidates) == 1:
        return candidates[0], "normalized filename"

    return None, None


def read_mrpack(mrpack_path: Path):
    with zipfile.ZipFile(mrpack_path) as z:
        index_data = json.loads(
            z.read("modrinth.index.json")
        )

        physical_files = {}

        for info in z.infolist():
            if info.is_dir():
                continue

            physical_files[info.filename] = info

        return index_data, physical_files


def read_cf_manifest(zip_path: Path):
    with zipfile.ZipFile(zip_path) as z:
        manifest = json.loads(
            z.read("manifest.json")
        )

    return manifest


def build_cf_manifest_index(manifest):
    result = {}

    for entry in manifest.get("files", []):
        project_id = entry.get("projectID")
        file_id = entry.get("fileID")

        if project_id is None or file_id is None:
            continue

        key = (
            int(project_id),
            int(file_id),
        )

        result[key] = entry

    return result


def find_mr_index_entry(
    mr_index_entries,
    filename,
    sha1=None,
    sha512=None,
):
    """
    Modrinth index側から既存エントリを探す。

    SHA1/SHA512 → filename → normalized filename
    の順で確認する。
    """

    if sha1:
        for entry in mr_index_entries:
            if not is_mod_index_file(
                entry.get("path", "")
            ):
                continue

            hashes = entry.get("hashes", {})

            if (
                isinstance(hashes, dict)
                and hashes.get("sha1", "").lower()
                == sha1.lower()
            ):
                return entry, "SHA1"

    if sha512:
        for entry in mr_index_entries:
            if not is_mod_index_file(
                entry.get("path", "")
            ):
                continue

            hashes = entry.get("hashes", {})

            if (
                isinstance(hashes, dict)
                and hashes.get("sha512", "").lower()
                == sha512.lower()
            ):
                return entry, "SHA512"

    candidates = []

    for entry in mr_index_entries:
        path = entry.get("path", "")

        if not is_mod_index_file(path):
            continue

        entry_filename = Path(path).name

        if (
            entry_filename.lower()
            == filename.lower()
        ):
            candidates.append(entry)

    if len(candidates) == 1:
        return candidates[0], "filename"

    normalized = normalize_filename(filename)

    candidates = [
        entry
        for entry in mr_index_entries
        if is_mod_index_file(
            entry.get("path", "")
        )
        and normalize_filename(
            Path(entry["path"]).name
        ) == normalized
    ]

    if len(candidates) == 1:
        return candidates[0], "normalized filename"

    return None, None


def make_cf_download_url(project_id, file_id):
    return (
        f"https://www.curseforge.com/api/v1/mods/"
        f"{project_id}/files/{file_id}/download"
    )


def get_existing_downloads(entry):
    downloads = entry.get("downloads")

    if not isinstance(downloads, list):
        return []

    return [
        value
        for value in downloads
        if isinstance(value, str)
        and value
    ]


def get_entry_hashes(entry):
    hashes = entry.get("hashes")

    if not isinstance(hashes, dict):
        return {}

    return hashes


def is_valid_download_url(url):
    return (
        isinstance(url, str)
        and (
            url.startswith("http://")
            or url.startswith("https://")
        )
    )


def find_cf_source(
    filename,
    prism,
    cf_manifest_index,
):
    if not prism:
        return None

    project_id = prism.get("project_id")
    file_id = prism.get("file_id")

    if project_id is None or file_id is None:
        return None

    manifest_entry = cf_manifest_index.get(
        (
            project_id,
            file_id,
        )
    )

    if not manifest_entry:
        return None

    return {
        "project_id": project_id,
        "file_id": file_id,
        "manifest": manifest_entry,
    }


def find_embedded_fallback(
    filename,
    sha1,
):
    """
    Prism metadata / CurseForge manifest から解決できない
    同梱Modについて、既知の公開配布元を解決する。

    ファイル名だけではなく、同梱実体のSHA1も照合する。
    """

    fallback = {
        "acedium-0.2.7-beta.jar": {
            "sha1": (
                "a8def1a80485ae2fb48e72bac0d44627634c8b1f"
            ),
            "url": (
                "https://github.com/ferriarnus/acedium/"
                "releases/download/v0.2.7-1.20.1/"
                "acedium-0.2.7-beta.jar"
            ),
            "source": (
                "GitHub: ferriarnus/acedium "
                "v0.2.7-1.20.1"
            ),
        },
        "create_tinkers_compat-2-forge-1.20.1.jar": {
            "sha1": (
                "f4b5301e6a597e033612bd3707d75765657ec08f"
            ),
            "url": make_cf_download_url(
                1212694,
                6445835,
            ),
            "source": (
                "CurseForge: "
                "project=1212694, file=6445835"
            ),
            "project_id": 1212694,
            "file_id": 6445835,
        },
    }

    info = fallback.get(
        filename.lower()
    )

    if info is None:
        return None

    if (
        info["sha1"].lower()
        != sha1.lower()
    ):
        return None

    return info


def process_mod_entry(
    entry,
    prism_indexes,
    cf_manifest_index,
    cf_file_indexes,
):
    path = entry.get("path", "")
    filename = Path(path).name

    new_entry = json.loads(
        json.dumps(entry)
    )

    existing_downloads = get_existing_downloads(
        entry
    )

    existing_hashes = get_entry_hashes(entry)

    existing_sha1 = existing_hashes.get(
        "sha1"
    )

    existing_sha512 = existing_hashes.get(
        "sha512"
    )

    cf_file, cf_file_match_method = find_file(
        filename,
        cf_file_indexes,
        existing_sha1,
        existing_sha512,
    )

    prism_sha1 = (
        cf_file["sha1"]
        if cf_file
        else existing_sha1
    )

    prism_sha512 = (
        cf_file["sha512"]
        if cf_file
        else existing_sha512
    )

    prism, prism_match_method = find_prism_metadata(
        filename,
        prism_indexes,
        prism_sha1,
        prism_sha512,
    )

    cf_source = find_cf_source(
        filename,
        prism,
        cf_manifest_index,
    )

    if cf_source:
        project_id = cf_source["project_id"]
        file_id = cf_source["file_id"]

        new_entry["downloads"] = [
            make_cf_download_url(
                project_id,
                file_id,
            )
        ]

        if cf_file:
            new_entry["hashes"] = {
                "sha1": cf_file["sha1"],
                "sha512": cf_file["sha512"],
            }

            new_entry["fileSize"] = len(
                cf_file["data"]
            )

        elif prism:
            if (
                prism.get("hash")
                and prism.get("hash_format")
            ):
                hash_format = (
                    prism["hash_format"].lower()
                )

                hashes = dict(
                    existing_hashes
                )

                if hash_format == "sha1":
                    hashes["sha1"] = prism["hash"]

                elif hash_format == "sha512":
                    hashes["sha512"] = prism["hash"]

                if hashes:
                    new_entry["hashes"] = hashes

        return {
            "entry": new_entry,
            "source": "curseforge",
            "filename": filename,
            "prism": prism,
            "prism_match_method": prism_match_method,
            "cf_file": cf_file,
            "cf_file_match_method": cf_file_match_method,
            "project_id": project_id,
            "file_id": file_id,
        }

    if cf_file:
        hashes = dict(existing_hashes)

        if not hashes.get("sha1"):
            hashes["sha1"] = cf_file["sha1"]

        if not hashes.get("sha512"):
            hashes["sha512"] = cf_file["sha512"]

        new_entry["hashes"] = hashes

        if "fileSize" not in new_entry:
            new_entry["fileSize"] = len(
                cf_file["data"]
            )

    if existing_downloads:
        return {
            "entry": new_entry,
            "source": "existing",
            "filename": filename,
            "prism": prism,
            "prism_match_method": prism_match_method,
            "cf_file": cf_file,
            "cf_file_match_method": cf_file_match_method,
            "project_id": None,
            "file_id": None,
        }

    return {
        "entry": new_entry,
        "source": "unresolved",
        "filename": filename,
        "prism": prism,
        "prism_match_method": prism_match_method,
        "cf_file": cf_file,
        "cf_file_match_method": cf_file_match_method,
        "project_id": None,
        "file_id": None,
    }


def build_embedded_mod_entry(
    physical_path,
    data,
    prism_indexes,
    cf_manifest_index,
    cf_file_indexes,
    mr_mod_entries,
):
    """
    overrides/mods に実体として入っていたModを、
    modrinth.index.jsonのエントリへ変換する。

    URL決定優先順位:

        1. Prism metadata の CurseForge project/file ID
        2. Prism metadata の直接URL
        3. 既知の外部配布元

    CurseForgeの場合は manifest に存在することも確認する。
    """

    filename = Path(physical_path).name

    sha1 = sha1_bytes(data)
    sha512 = sha512_bytes(data)

    # --------------------------------------------------
    # 既存indexに同じ実体が存在するか
    # --------------------------------------------------

    existing_entry, existing_match_method = (
        find_mr_index_entry(
            mr_mod_entries,
            filename,
            sha1,
            sha512,
        )
    )

    if existing_entry:
        return {
            "status": "existing",
            "entry": existing_entry,
            "filename": filename,
            "sha1": sha1,
            "sha512": sha512,
            "match_method": existing_match_method,
        }

    # --------------------------------------------------
    # Prism metadata
    # --------------------------------------------------

    prism, prism_match_method = find_prism_metadata(
        filename,
        prism_indexes,
        sha1,
        sha512,
    )

    # --------------------------------------------------
    # ダウンロードURL決定
    # --------------------------------------------------

    download_url = None
    source = None

    project_id = None
    file_id = None

    # --------------------------------------------------
    # Prism metadataがある場合
    # --------------------------------------------------

    if prism:
        project_id = prism.get(
            "project_id"
        )

        file_id = prism.get(
            "file_id"
        )

        # --------------------------------------------------
        # CurseForge
        # --------------------------------------------------

        cf_source = find_cf_source(
            filename,
            prism,
            cf_manifest_index,
        )

        if cf_source:
            download_url = make_cf_download_url(
                cf_source["project_id"],
                cf_source["file_id"],
            )

            source = "curseforge"

            project_id = cf_source[
                "project_id"
            ]

            file_id = cf_source[
                "file_id"
            ]

        # --------------------------------------------------
        # Prism metadataの直接URL
        # --------------------------------------------------

        elif is_valid_download_url(
            prism.get("download")
        ):
            download_url = prism[
                "download"
            ]

            source = "prism"

    # --------------------------------------------------
    # 既知の外部配布元フォールバック
    # --------------------------------------------------

    if not download_url:
        fallback = find_embedded_fallback(
            filename,
            sha1,
        )

        if fallback:
            download_url = fallback[
                "url"
            ]

            source = fallback[
                "source"
            ]

            project_id = fallback.get(
                "project_id"
            )

            file_id = fallback.get(
                "file_id"
            )

    # --------------------------------------------------
    # URLが無い
    # --------------------------------------------------

    if not download_url:
        return {
            "status": "unresolved",
            "entry": None,
            "filename": filename,
            "sha1": sha1,
            "sha512": sha512,
            "match_method": None,
            "prism": prism,
            "prism_match_method": prism_match_method,
            "source": None,
            "project_id": None,
            "file_id": None,
        }

    # --------------------------------------------------
    # 新しいindex entry
    # --------------------------------------------------

    new_entry = {
        "path": f"mods/{filename}",
        "hashes": {
            "sha1": sha1,
            "sha512": sha512,
        },
        "downloads": [
            download_url,
        ],
        "fileSize": len(data),
        "env": {
            "client": "required",
            "server": "required",
        },
    }

    return {
        "status": "added",
        "entry": new_entry,
        "filename": filename,
        "sha1": sha1,
        "sha512": sha512,
        "match_method": None,
        "prism": prism,
        "prism_match_method": prism_match_method,
        "source": source,
        "project_id": project_id,
        "file_id": file_id,
    }


def main():
    if len(sys.argv) not in (4, 5):
        print("Usage:")
        print(
            "  py build_mrpack.py "
            "BASE.mrpack CF.zip OUTPUT.mrpack "
            "[PRISM_INSTANCE_DIR]"
        )
        sys.exit(1)

    mrpack_path = Path(
        sys.argv[1]
    )

    cf_zip_path = Path(
        sys.argv[2]
    )

    output_path = Path(
        sys.argv[3]
    )

    prism_instance = (
        Path(sys.argv[4])
        if len(sys.argv) >= 5
        else None
    )

    # ------------------------------------------------------
    # 入力解析
    # ------------------------------------------------------

    print("=== 入力解析 ===")
    print()

    print("Modrinth export...")

    mr_index, mr_physical_files = read_mrpack(
        mrpack_path
    )

    mr_index_files = mr_index.get(
        "files",
        [],
    )

    mr_mod_entries = [
        entry
        for entry in mr_index_files
        if is_mod_index_file(
            entry.get("path", "")
        )
    ]

    print(
        f"  index entries: "
        f"{len(mr_index_files)}"
    )

    print(
        f"  mod entries: "
        f"{len(mr_mod_entries)}"
    )

    physical_mod_files = [
        name
        for name in mr_physical_files
        if is_mod_file(name)
    ]

    physical_mod_jars = [
        name
        for name in physical_mod_files
        if name.lower().endswith(".jar")
    ]

    physical_mod_zips = [
        name
        for name in physical_mod_files
        if name.lower().endswith(".zip")
    ]

    print(
        f"  physical mods JAR: "
        f"{len(physical_mod_jars)}"
    )

    print(
        f"  physical mods ZIP: "
        f"{len(physical_mod_zips)}"
    )

    print(
        f"  physical mods total: "
        f"{len(physical_mod_files)}"
    )

    print()
    print("CurseForge export...")

    cf_files = read_zip_files(
        cf_zip_path
    )

    cf_jars = [
        file
        for file in cf_files
        if file["filename"]
        .lower()
        .endswith(".jar")
    ]

    cf_zips = [
        file
        for file in cf_files
        if file["filename"]
        .lower()
        .endswith(".zip")
    ]

    print(
        f"  JAR: {len(cf_jars)}"
    )

    print(
        f"  ZIP: {len(cf_zips)}"
    )

    manifest = read_cf_manifest(
        cf_zip_path
    )

    cf_manifest_index = (
        build_cf_manifest_index(
            manifest
        )
    )

    print("CurseForge manifest...")

    print(
        f"  entries: "
        f"{len(cf_manifest_index)}"
    )

    # ------------------------------------------------------
    # Prism
    # ------------------------------------------------------

    prism_metadata = []
    prism_indexes = {
        "filename": {},
        "normalized_filename": {},
        "hash": {},
    }

    if prism_instance:
        print("Prism .pw.toml...")

        prism_metadata = read_prism_metadata(
            prism_instance
        )

        prism_indexes = build_prism_indexes(
            prism_metadata
        )

        print(
            f"  metadata: "
            f"{len(prism_metadata)}"
        )

        metadata_dirs = (
            get_prism_metadata_dirs(
                prism_instance
            )
        )

        if len(metadata_dirs) > 1:
            print(
                "  fallback: "
                f"{metadata_dirs[1]}"
            )

    # ------------------------------------------------------
    # CFファイルindex
    # ------------------------------------------------------

    cf_file_indexes = build_file_indexes(
        cf_files
    )

    # ------------------------------------------------------
    # index上の317個を処理
    # ------------------------------------------------------

    print()
    print("=== index上Mod照合 ===")
    print()

    results = []
    unresolved = []

    for entry in mr_mod_entries:
        filename = Path(
            entry["path"]
        ).name

        print(
            f"[??] {filename}"
        )

        result = process_mod_entry(
            entry,
            prism_indexes,
            cf_manifest_index,
            cf_file_indexes,
        )

        results.append(result)

        source = result["source"]

        if source == "curseforge":
            print(
                "     source: CurseForge"
            )

            print(
                f"     Prism match: "
                f"{result['prism_match_method']}"
            )

            print(
                f"     CF: "
                f"project={result['project_id']}, "
                f"file={result['file_id']}"
            )

        elif source == "existing":
            print(
                "     source: existing download"
            )

            downloads = get_existing_downloads(
                result["entry"]
            )

            if downloads:
                print(
                    f"     URL: "
                    f"{downloads[0]}"
                )

        else:
            print(
                "     source: UNRESOLVED"
            )

            unresolved.append(result)

        print()

    # ------------------------------------------------------
    # 既存317個の結果
    # ------------------------------------------------------

    curseforge_count = sum(
        1
        for result in results
        if result["source"] == "curseforge"
    )

    existing_count = sum(
        1
        for result in results
        if result["source"] == "existing"
    )

    unresolved_count = sum(
        1
        for result in results
        if result["source"] == "unresolved"
    )

    classification_count = (
        curseforge_count
        + existing_count
        + unresolved_count
    )

    print("=== 結果 ===")
    print()

    print(
        f"対象Mod:             "
        f"{len(mr_mod_entries)}"
    )

    print(
        f"CurseForge化:        "
        f"{curseforge_count}"
    )

    print(
        f"既存URL維持:         "
        f"{existing_count}"
    )

    print(
        f"未解決:              "
        f"{unresolved_count}"
    )

    print(
        f"分類合計:             "
        f"{classification_count}"
    )

    if classification_count != len(
        mr_mod_entries
    ):
        raise RuntimeError(
            "Mod classification count mismatch."
        )

    if unresolved:
        print()
        print("=== 未解決一覧 ===")
        print()

        for result in unresolved:
            print(
                f"  - {result['filename']}"
            )

        print()

        raise RuntimeError(
            "There are unresolved mods in "
            "modrinth.index.json."
        )

    # ------------------------------------------------------
    # 同梱Modをindexへ追加
    # ------------------------------------------------------

    print()
    print("=== 同梱Mod移行 ===")
    print()

    embedded_results = []
    embedded_unresolved = []

    with zipfile.ZipFile(
        mrpack_path,
        "r",
    ) as src:

        for physical_path in physical_mod_files:
            print(
                f"[??] {physical_path}"
            )

            data = src.read(
                physical_path
            )

            result = build_embedded_mod_entry(
                physical_path,
                data,
                prism_indexes,
                cf_manifest_index,
                cf_file_indexes,
                mr_mod_entries,
            )

            embedded_results.append(result)

            status = result["status"]

            if status == "existing":
                print(
                    f"     already indexed: "
                    f"{result['match_method']}"
                )

                print(
                    f"     index path: "
                    f"{result['entry']['path']}"
                )

            elif status == "added":
                print(
                    f"     added: "
                    f"{result['source']}"
                )

                print(
                    f"     index path: "
                    f"{result['entry']['path']}"
                )

                print(
                    f"     URL: "
                    f"{result['entry']['downloads'][0]}"
                )

                if result.get("project_id") is not None:
                    print(
                        f"     CF: "
                        f"project={result['project_id']}, "
                        f"file={result['file_id']}"
                    )

            else:
                print(
                    "     UNRESOLVED"
                )

                print(
                    f"     SHA1: "
                    f"{result['sha1']}"
                )

                print(
                    f"     SHA512: "
                    f"{result['sha512']}"
                )

                prism = result.get("prism")

                if prism:
                    print(
                        f"     Prism: "
                        f"{prism.get('filename')}"
                    )

                    print(
                        f"     Prism match: "
                        f"{result.get('prism_match_method')}"
                    )

                    print(
                        f"     CF project: "
                        f"{prism.get('project_id')}"
                    )

                    print(
                        f"     CF file: "
                        f"{prism.get('file_id')}"
                    )

                    print(
                        f"     download: "
                        f"{prism.get('download')}"
                    )

                embedded_unresolved.append(
                    result
                )

            print()

    embedded_added_count = sum(
        1
        for result in embedded_results
        if result["status"] == "added"
    )

    embedded_existing_count = sum(
        1
        for result in embedded_results
        if result["status"] == "existing"
    )

    embedded_unresolved_count = sum(
        1
        for result in embedded_results
        if result["status"] == "unresolved"
    )

    print("=== 同梱Mod移行結果 ===")
    print()

    print(
        f"同梱Mod実体:         "
        f"{len(physical_mod_files)}"
    )

    print(
        f"indexへ追加:         "
        f"{embedded_added_count}"
    )

    print(
        f"既存index一致:       "
        f"{embedded_existing_count}"
    )

    print(
        f"未解決:              "
        f"{embedded_unresolved_count}"
    )

    # ------------------------------------------------------
    # 未解決の同梱Modがある場合
    # ------------------------------------------------------

    if embedded_unresolved:
        print()
        print(
            "[ERROR] "
            "再ダウンロードURLを特定できない"
            "同梱Modがあります。"
        )

        print()

        for result in embedded_unresolved:
            print(
                f"  - {result['filename']}"
            )

        print()

        print(
            "これらを削除すると再ダウンロード時に"
            "Modが欠落するため、MRPack生成を中止します。"
        )

        raise RuntimeError(
            "Some embedded mods cannot be "
            "represented as downloadable index entries."
        )

    # ------------------------------------------------------
    # index.jsonへ追加するエントリ
    # ------------------------------------------------------

    embedded_entries = [
        result["entry"]
        for result in embedded_results
        if result["status"] == "added"
    ]

    # ------------------------------------------------------
    # index.json再構築
    # ------------------------------------------------------

    print()
    print("=== index.json再構築 ===")
    print()

    new_index = json.loads(
        json.dumps(mr_index)
    )

    result_by_path = {
        result["entry"]["path"]: result
        for result in results
    }

    new_files = []

    for file_entry in new_index.get(
        "files",
        [],
    ):
        path = file_entry.get(
            "path",
            "",
        )

        if is_mod_index_file(path):
            result = result_by_path.get(
                path
            )

            if result:
                new_files.append(
                    result["entry"]
                )
            else:
                new_files.append(
                    file_entry
                )

            continue

        new_files.append(
            file_entry
        )

    # ------------------------------------------------------
    # 同梱Modをindexへ追加
    # ------------------------------------------------------

    for embedded_entry in embedded_entries:
        new_files.append(
            embedded_entry
        )

        print(
            f"  add: "
            f"{embedded_entry['path']}"
        )

    new_index["files"] = new_files

    # ------------------------------------------------------
    # 最終的なindex上Mod数を検証
    # ------------------------------------------------------

    new_mod_entries = [
        entry
        for entry in new_index.get(
            "files",
            [],
        )
        if is_mod_index_file(
            entry.get("path", "")
        )
    ]

    expected_mod_count = (
        len(mr_mod_entries)
        + len(physical_mod_files)
    )

    actual_mod_count = len(
        new_mod_entries
    )

    print()
    print("=== index検証 ===")
    print()

    print(
        f"元index上Mod:        "
        f"{len(mr_mod_entries)}"
    )

    print(
        f"同梱Mod:              "
        f"{len(physical_mod_files)}"
    )

    print(
        f"期待index上Mod:      "
        f"{expected_mod_count}"
    )

    print(
        f"実際index上Mod:      "
        f"{actual_mod_count}"
    )

    if actual_mod_count != expected_mod_count:
        raise RuntimeError(
            "Final modrinth.index.json mod count "
            "does not match the expected mod count."
        )

    print(
        "[OK] "
        f"{actual_mod_count}個のModをindexへ登録しました。"
    )

    # ------------------------------------------------------
    # 出力MRPack生成
    # ------------------------------------------------------

    print()
    print("=== MRPack生成 ===")

    if (
        output_path.resolve()
        == mrpack_path.resolve()
    ):
        raise RuntimeError(
            "OUTPUT.mrpack must be different "
            "from BASE.mrpack"
        )

    removed_mod_files = []

    with zipfile.ZipFile(
        mrpack_path,
        "r",
    ) as src, zipfile.ZipFile(
        output_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as dst:

        for info in src.infolist():
            name = info.filename

            # --------------------------------------------------
            # 元indexは再構築する
            # --------------------------------------------------

            if name == "modrinth.index.json":
                continue

            # --------------------------------------------------
            # 同梱Mod実体は削除
            # --------------------------------------------------

            if is_mod_file(name):
                print(
                    f"  remove: {name}"
                )

                removed_mod_files.append(
                    name
                )

                continue

            # --------------------------------------------------
            # その他のファイルはそのままコピー
            # --------------------------------------------------

            data = src.read(name)

            dst.writestr(
                info,
                data,
            )

        # --------------------------------------------------
        # 再構築したindex.json
        # --------------------------------------------------

        index_json = json.dumps(
            new_index,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")

        dst.writestr(
            "modrinth.index.json",
            index_json,
        )

    # ------------------------------------------------------
    # remove数確認
    # ------------------------------------------------------

    removed_count = len(
        removed_mod_files
    )

    physical_mod_count = len(
        physical_mod_files
    )

    print()
    print("=== 除去結果 ===")
    print()

    print(
        f"元MRPack同梱Mod:     "
        f"{physical_mod_count}"
    )

    print(
        f"remove実績:          "
        f"{removed_count}"
    )

    if removed_count != physical_mod_count:
        raise RuntimeError(
            "Removed mod count does not match "
            "the number of physical mod files."
        )

    print(
        "[OK] "
        "同梱Mod実体を全て除去しました。"
    )

    # ------------------------------------------------------
    # 最終確認
    # ------------------------------------------------------

    print()
    print("=== 最終確認 ===")
    print()

    output_mod_files = []
    output_mod_entries = []

    with zipfile.ZipFile(
        output_path,
        "r",
    ) as z:
        output_index = json.loads(
            z.read("modrinth.index.json")
        )

        for info in z.infolist():
            if info.is_dir():
                continue

            if is_mod_file(info.filename):
                output_mod_files.append(
                    info.filename
                )

        output_mod_entries = [
            entry
            for entry in output_index.get(
                "files",
                [],
            )
            if is_mod_index_file(
                entry.get("path", "")
            )
        ]

    # --------------------------------------------------
    # 実体0確認
    # --------------------------------------------------

    if output_mod_files:
        print(
            "[ERROR] "
            "再頒布用Mod実体が残っています:"
        )

        for name in output_mod_files:
            print(
                f"  - {name}"
            )

        raise RuntimeError(
            "Output MRPack still contains "
            "redistributable mod files."
        )

    print(
        "[OK] overrides/mods/*.jar: 0"
    )

    print(
        "[OK] overrides/mods/*.zip: 0"
    )

    # --------------------------------------------------
    # index 366確認
    # --------------------------------------------------

    print(
        f"[OK] index上Mod: "
        f"{len(output_mod_entries)}"
    )

    if len(output_mod_entries) != expected_mod_count:
        raise RuntimeError(
            "Output index mod count mismatch."
        )

    print(
        f"[OK] "
        f"{len(mr_mod_entries)} "
        f"+ "
        f"{len(physical_mod_files)} "
        f"= "
        f"{len(output_mod_entries)}"
    )

    print()
    print(
        f"[OK] MRPack generated: "
        f"{output_path}"
    )


if __name__ == "__main__":
    main()
