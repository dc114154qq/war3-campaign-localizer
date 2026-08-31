from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import tempfile
from pathlib import Path

try:
    import pympq
except ImportError as exc:
    raise SystemExit(
        "pympq is required for archive verification. Run this script with the "
        "Python environment that contains pympq/StormLib."
    ) from exc


SFILE_INFO_FLAGS = 53


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def find_stormlib(explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    module_path = Path(pympq.__file__).resolve()
    candidates.extend(
        [
            module_path.parent / "StormLib.dll",
            module_path.parent.parent / "StormLib.dll",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "StormLib.dll was not found beside pympq. Pass its path with --stormlib."
    )


class StormInfo:
    def __init__(self, dll_path: Path):
        self.dll = C.WinDLL(str(dll_path))
        self.handle = C.c_void_p
        self.dword = C.c_uint32
        self.dll.SFileOpenArchive.argtypes = [
            C.c_wchar_p,
            self.dword,
            self.dword,
            C.POINTER(self.handle),
        ]
        self.dll.SFileOpenArchive.restype = C.c_bool
        self.dll.SFileCloseArchive.argtypes = [self.handle]
        self.dll.SFileCloseArchive.restype = C.c_bool
        self.dll.SFileOpenFileEx.argtypes = [
            self.handle,
            C.c_char_p,
            self.dword,
            C.POINTER(self.handle),
        ]
        self.dll.SFileOpenFileEx.restype = C.c_bool
        self.dll.SFileCloseFile.argtypes = [self.handle]
        self.dll.SFileCloseFile.restype = C.c_bool
        self.dll.SFileGetFileInfo.argtypes = [
            self.handle,
            C.c_int,
            C.c_void_p,
            self.dword,
            C.POINTER(self.dword),
        ]
        self.dll.SFileGetFileInfo.restype = C.c_bool

    def flags(self, archive: Path, name: str) -> int:
        archive_handle = self.handle()
        if not self.dll.SFileOpenArchive(str(archive), 0, 0, C.byref(archive_handle)):
            raise OSError(C.get_last_error(), f"cannot open archive {archive}")
        try:
            file_handle = self.handle()
            if not self.dll.SFileOpenFileEx(
                archive_handle, name.encode("utf-8"), 0, C.byref(file_handle)
            ):
                raise FileNotFoundError(f"{archive}: {name}")
            try:
                value = self.dword()
                needed = self.dword()
                if not self.dll.SFileGetFileInfo(
                    file_handle,
                    SFILE_INFO_FLAGS,
                    C.byref(value),
                    C.sizeof(value),
                    C.byref(needed),
                ):
                    raise OSError(
                        C.get_last_error(), f"cannot read entry flags for {name}"
                    )
                return int(value.value)
            finally:
                self.dll.SFileCloseFile(file_handle)
        finally:
            self.dll.SFileCloseArchive(archive_handle)


def extract_entry(archive: Path, name: str, destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with pympq.open_archive(
        str(archive), [pympq.MPQ_OPEN_READ_ONLY]
    ) as handle:
        if not handle.has_file(name):
            return {"present": False}
        handle.extract_file(name, str(destination))
    return {
        "present": True,
        "size": destination.stat().st_size,
        "sha256": sha256(destination),
    }


def read_listfile(archive: Path, directory: Path, label: str) -> tuple[list[str], dict]:
    output = directory / f"{label}-listfile.txt"
    info = extract_entry(archive, "(listfile)", output)
    if not info["present"]:
        return [], info
    raw = output.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    names = []
    seen = set()
    for line in text.splitlines():
        name = line.strip()
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names, info


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare all known files and MPQ entry flags in two archives"
    )
    parser.add_argument("--original", required=True)
    parser.add_argument("--rebuilt", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--changed-entry", action="append", default=[])
    parser.add_argument("--required-entry", action="append", default=[])
    parser.add_argument("--stormlib")
    args = parser.parse_args()

    original = Path(args.original).resolve()
    rebuilt = Path(args.rebuilt).resolve()
    if not original.is_file():
        raise FileNotFoundError(original)
    if not rebuilt.is_file():
        raise FileNotFoundError(rebuilt)

    storm = StormInfo(find_stormlib(args.stormlib))
    changed = set(args.changed_entry)
    required = set(args.required_entry)
    errors: list[dict] = []
    entries: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="war3-archive-verify-") as temp_name:
        temp = Path(temp_name)
        original_names, original_listfile = read_listfile(
            original, temp, "original"
        )
        rebuilt_names, rebuilt_listfile = read_listfile(rebuilt, temp, "rebuilt")
        if not original_listfile["present"]:
            errors.append(
                {"entry": "(listfile)", "error": "original archive lacks listfile"}
            )
        if not rebuilt_listfile["present"]:
            errors.append(
                {"entry": "(listfile)", "error": "rebuilt archive lacks listfile"}
            )

        known_names = set(original_names) | set(rebuilt_names) | required | changed
        known_names.add("(listfile)")
        for index, name in enumerate(sorted(known_names, key=str.lower)):
            source_info = extract_entry(
                original, name, temp / "original" / f"{index:06d}.bin"
            )
            rebuilt_info = extract_entry(
                rebuilt, name, temp / "rebuilt" / f"{index:06d}.bin"
            )
            item = {
                "entry": name,
                "declared_changed": name in changed,
                "original": source_info,
                "rebuilt": rebuilt_info,
            }
            if source_info["present"]:
                item["original"]["flags"] = storm.flags(original, name)
            if rebuilt_info["present"]:
                item["rebuilt"]["flags"] = storm.flags(rebuilt, name)

            if name in required and not rebuilt_info["present"]:
                errors.append({"entry": name, "error": "required entry is missing"})
            if source_info["present"] != rebuilt_info["present"]:
                errors.append(
                    {
                        "entry": name,
                        "error": "entry presence differs between archives",
                    }
                )
            elif source_info["present"] and rebuilt_info["present"]:
                if source_info["flags"] != rebuilt_info["flags"]:
                    errors.append(
                        {
                            "entry": name,
                            "error": "MPQ entry flags differ",
                            "original": source_info["flags"],
                            "rebuilt": rebuilt_info["flags"],
                        }
                    )
                content_changed = (
                    source_info["size"] != rebuilt_info["size"]
                    or source_info["sha256"] != rebuilt_info["sha256"]
                )
                item["content_changed"] = content_changed
                if content_changed and name not in changed:
                    errors.append(
                        {
                            "entry": name,
                            "error": "undeclared content change",
                        }
                    )
                if not content_changed and name in changed:
                    item["warning"] = "declared changed but content is identical"
            entries.append(item)

    report = {
        "original": str(original),
        "rebuilt": str(rebuilt),
        "original_listfile_entries": len(original_names),
        "rebuilt_listfile_entries": len(rebuilt_names),
        "known_entries_checked": len(entries),
        "changed_entries": sorted(changed),
        "required_entries": sorted(required),
        "errors": errors,
        "entries": entries,
        "archive_check_passed": not errors,
        "client_compatibility_proven": False,
        "client_compatibility_note": (
            "Archive verification does not replace smoke tests in Warcraft III "
            "1.31 and the target Reforged build."
        ),
    }
    output = Path(args.report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"errors": len(errors), "entries": len(entries)}))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

