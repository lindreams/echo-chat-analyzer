"""Offline PIC-1 experiment; reads only a manifest and explicitly listed copies.

Run with the verified source environment (PYTHONPATH=src). Never acquires a DB,
loads user configuration, contacts NapCat, or follows paths inside messages.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import time

from qq_chat_analyzer.qq_db_adapter import _content_from_segment, _protobuf_fields, _read_varint
from qq_chat_analyzer.application.sticker_media import (
    _Rejected, _inspect, _no_links, _open_original, _witness,
)


TAGS = (45003, 45406, 45424, 45416, 45418, 45403, 45812)


class ProbeError(Exception):
    """Only fixed, non-private reason codes may reach stdout."""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ProbeError("invalid_arguments")


def local_path(value):
    path = Path(value)
    if (not path.is_absolute() or ".." in path.parts or path.drive.startswith("\\\\")
            or str(path).startswith("\\\\")):
        raise ProbeError("invalid_local_path")
    _no_links(path)
    return path.resolve(strict=True)


def read_copy(path, root, limit):
    with _open_original(path, root) as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > limit:
            raise ProbeError("file_budget")
        raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ProbeError("file_budget")
        if _witness(before) != _witness(os.fstat(stream.fileno())):
            raise ProbeError("file_changed")
        return raw


def fields(data):
    """Reuse production values; inventory fixed wire types it intentionally skips."""
    fixed = []
    offset = 0
    while offset < len(data):
        key = _read_varint(data, offset)
        if key is None:
            raise ProbeError("invalid_message_blob")
        key, offset = key
        tag, wire = key >> 3, key & 7
        if not 0 < tag < 2 ** 29:
            raise ProbeError("invalid_message_blob")
        if wire in (0, 2):
            value = _read_varint(data, offset)
            if value is None:
                raise ProbeError("invalid_message_blob")
            value, offset = value
            if wire == 2:
                offset += value
        elif wire in (1, 5):
            fixed.append((tag, wire, None))
            offset += 8 if wire == 1 else 4
        else:
            raise ProbeError("invalid_message_blob")
        if offset > len(data):
            raise ProbeError("invalid_message_blob")
    return (*_protobuf_fields(data), *fixed)


def pic_fields(sample):
    if not isinstance(sample, dict) or sample.get("known_class") not in ("ordinary", "custom", "unknown"):
        raise ProbeError("invalid_sample")
    encoded = sample.get("message_blob")
    index = sample.get("pic_index")
    if not isinstance(encoded, str) or len(encoded) > 90_000 or type(index) is not int or not 0 <= index < 16:
        raise ProbeError("invalid_sample")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ProbeError("invalid_message_blob") from None
    if not raw or len(raw) > 65536:
        raise ProbeError("invalid_message_blob")
    pics = []
    for tag, wire, value in fields(raw):
        if tag == 40800 and wire == 2:
            segment = fields(value)
            types = [v for t, w, v in segment if t == 45002 and w == 0]
            if types == [2]:
                pics.append(segment)
    if index >= len(pics):
        raise ProbeError("pic_not_found")
    return pics[index]


def digest_value(tag, wire, value):
    if tag not in (45406, 45424) or wire != 2:
        return None
    if len(value) == 16:
        return value.hex()
    if re.fullmatch(b"[0-9a-fA-F]{32}", value):
        return value.decode("ascii").lower()
    return None


def probe(manifest, root):
    if not isinstance(manifest, dict):
        raise ProbeError("invalid_manifest")
    samples, names = manifest.get("samples"), manifest.get("media")
    if not isinstance(samples, list) or not 1 <= len(samples) <= 16:
        raise ProbeError("sample_budget")
    if not isinstance(names, list) or len(names) > 16:
        raise ProbeError("media_budget")
    # Validate the complete selection before reading any media. Never enumerate.
    for name in names:
        if (not isinstance(name, str) or not name or "\\" in name or ":" in name
                or "\x00" in name or Path(name).is_absolute()
                or PureWindowsPath(name).is_absolute()
                or any(p in ("..", ".", "") for p in name.split("/"))):
            raise ProbeError("invalid_media_path")
    selected = [pic_fields(sample) for sample in samples]
    media = []
    matches = {}
    total = 0
    deadline = time.monotonic() + 10
    for index, name in enumerate(names, 1):
        if time.monotonic() > deadline:
            raise ProbeError("time_budget")
        candidate = f"m{index}"
        item = {"candidate": candidate}
        try:
            raw = read_copy(root / name, root, min(16 * 1024 ** 2, 64 * 1024 ** 2 - total))
            total += len(raw)
            digest = hashlib.md5(raw).hexdigest()
            matches.setdefault(digest, []).append(candidate)
            fmt, count = _inspect(raw, max_pixels=8 * 1024 ** 2, max_frames=32)
            item.update(status="valid_image", format=fmt, frame_count=count)
        except _Rejected as error:
            item.update(status=error.status, reason=error.reason)
        except FileNotFoundError:
            item.update(status="missing", reason="selected_file_missing")
        except OSError:
            item.update(status="unreadable", reason="selected_file_unreadable")
        media.append(item)
    if time.monotonic() > deadline:
        raise ProbeError("time_budget")
    valid = {m["candidate"] for m in media if m["status"] == "valid_image"}
    aliases = {}
    rows = []
    classes = {"ordinary": set(), "custom": set()}
    incomplete_labels = False
    for index, (sample, segment) in enumerate(zip(samples, selected), 1):
        row = {"sample": f"s{index}", "known_class": sample["known_class"], "fields": {},
               "original_association": "not_established"}
        digests = {}
        for tag in TAGS:
            observations = []
            occurrences = [(w, v) for t, w, v in segment if t == tag]
            for wire, value in occurrences:
                observation = {"wire_type": wire, "category": "unexpected_wire_type"}
                digest = digest_value(tag, wire, value)
                if tag in (45406, 45424) and wire == 2:
                    observation["category"] = "invalid_digest"
                    if digest:
                        observation.update(category="md5_raw16" if len(value) == 16 else "md5_hex32",
                                           digest=aliases.setdefault(digest, f"d{len(aliases) + 1}"),
                                           matches=matches.get(digest, []))
                elif tag in (45403, 45812) and wire == 2:
                    observation["category"] = "path_hint_not_followed"
                elif tag in (45003, 45416, 45418) and wire == 0:
                    # Bounded numeric evidence only; never echo arbitrary integers/text.
                    limit = 4096 if tag == 45416 else 255 if tag == 45003 else 1
                    observation["category"] = "integer" if 0 <= value <= limit else "out_of_range"
                    if observation["category"] == "integer":
                        observation["value"] = value
                observations.append(observation)
            row["fields"][str(tag)] = {"present": bool(occurrences), "observations": observations}
            if tag in (45406, 45424):
                # Repeated conflicting or wrong-wire values cannot authorize a conclusion.
                values = [digest_value(tag, w, v) for w, v in occurrences]
                digests[tag] = values[0] if values and all(v == values[0] for v in values) else None
        a, b = digests[45406], digests[45424]
        row["digest_relation"] = ("same" if a == b else "different") if a and b else "not_comparable"
        row["both_digests_match_valid_images"] = (
            bool(set(matches.get(a, [])) & valid) and bool(set(matches.get(b, [])) & valid)
        ) if a and b else None
        production = _content_from_segment(tuple(segment), 0)
        row["production_digest"] = "retained" if production.media and production.media.content_md5 else "not_retained"
        subtypes = row["fields"]["45003"]["observations"]
        if (sample["known_class"] in classes and len(subtypes) == 1
                and subtypes[0]["category"] == "integer"):
            classes[sample["known_class"]].add(subtypes[0]["value"])
        elif sample["known_class"] in classes:
            incomplete_labels = True
        rows.append(row)
    comparison = "insufficient_labeled_samples"
    if not incomplete_labels and classes["ordinary"] and classes["custom"]:
        comparison = ("overlap_in_selected_labels" if classes["ordinary"] & classes["custom"]
                      else "separates_selected_labels_only")
    return {"schema": "echo-pic-1", "scope": "selected_samples_only", "napcat": "not_observed",
            "pic_subtype_mapping": "not_observed", "classification_comparison": comparison,
            "samples": rows, "media": media}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProbeError("duplicate_json_key")
        result[key] = value
    return result


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("--input", required=True, help="Explicit selected-message manifest")
    parser.add_argument("--media-root", required=True, help="Authorized directory of selected copies")
    try:
        args = parser.parse_args(argv)
        source, root = local_path(args.input), local_path(args.media_root)
        if not root.is_dir():
            raise ProbeError("invalid_media_root")
        manifest = json.loads(read_copy(source, source.parent, 2 * 1024 ** 2).decode("utf-8-sig"),
                              object_pairs_hook=unique_object)
        report = probe(manifest, root)
    except ProbeError as error:
        report = {"error": str(error)}
    except _Rejected as error:
        report = {"error": error.reason}
    except (OSError, ValueError, TypeError, RecursionError):
        report = {"error": "invalid_or_unreadable_input"}
    print(json.dumps(report, ensure_ascii=True))
    return 2 if "error" in report else 0


if __name__ == "__main__":
    raise SystemExit(main())
