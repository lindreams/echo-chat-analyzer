"""PIC-1 diagnostics use fictional messages and explicitly listed media only."""
import base64
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

from test_qq_db_rich_contents import _bytes, _scalar


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "qq_pic_probe.py"
pytestmark = pytest.mark.slow_integration  # Real CLI subprocess, always fictional inputs.


def picture(fmt="PNG", color="red", animated=False):
    stream = BytesIO()
    options = dict(save_all=True, append_images=[Image.new("RGB", (3, 2), "blue")],
                   duration=100, loop=0) if animated else {}
    Image.new("RGB", (3, 2), color).save(stream, format=fmt, **options)
    return stream.getvalue()


def sample(raw, subtype, known_class, alternate=None, extra=b""):
    body = (_scalar(45002, 2) + _scalar(45003, subtype)
            + _bytes(45406, hashlib.md5(raw).digest())
            + _scalar(45416, 1001) + _scalar(45418, 1) + extra)
    if alternate is not None:
        body += _bytes(45424, alternate)
    return {"message_blob": base64.b64encode(_bytes(40800, body)).decode(),
            "pic_index": 0, "known_class": known_class}


def run_probe(tmp_path, samples, files, *, entries=None):
    root = tmp_path / "copies"
    root.mkdir(exist_ok=True)
    for name, raw in files.items():
        (root / name).write_bytes(raw)
    manifest = tmp_path / "selected.json"
    manifest.write_text(json.dumps({"samples": samples,
                                    "media": entries if entries is not None else list(files)}),
                        encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), "--input", str(manifest),
                             "--media-root", str(root)], capture_output=True, text=True,
                            timeout=20)
    return result


def successful(result):
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    return json.loads(result.stdout)


def test_png_labels_and_repeated_gif_have_private_cross_sample_evidence(tmp_path):
    png, gif, other = picture(), picture("GIF", animated=True), picture(color="green")
    samples = [sample(png, 0, "ordinary"), sample(png, 1, "custom"),
               sample(gif, 1, "custom"), sample(gif, 1, "custom"),
               sample(other, 1, "custom")]
    report = successful(run_probe(tmp_path, samples, {"private-name.bin": png, "b": gif, "c": other}))
    assert report["napcat"] == report["pic_subtype_mapping"] == "not_observed"
    assert report["classification_comparison"] == "separates_selected_labels_only"
    rows = report["samples"]
    observations = [row["fields"]["45406"]["observations"][0] for row in rows]
    assert [o["digest"] for o in observations] == ["d1", "d1", "d2", "d2", "d3"]
    assert [o["matches"] for o in observations] == [["m1"], ["m1"], ["m2"], ["m2"], ["m3"]]
    assert report["media"][1]["format"] == "GIF"
    assert report["media"][1]["frame_count"] == 2
    assert all(r["original_association"] == "not_established" for r in rows)
    for private in (str(tmp_path), "private-name", hashlib.md5(png).hexdigest(),
                    samples[0]["message_blob"]):
        assert private not in json.dumps(report)


def test_distinct_digests_can_match_two_valid_images_without_weakening_production(tmp_path):
    first, second = picture(), picture(color="green")
    report = successful(run_probe(tmp_path, [sample(first, 1, "custom",
        hashlib.md5(second).hexdigest().upper().encode())], {"a": first, "b": second}))
    row = report["samples"][0]
    assert row["digest_relation"] == "different"
    assert row["both_digests_match_valid_images"] is True
    assert row["fields"]["45424"]["observations"][0]["category"] == "md5_hex32"
    assert row["production_digest"] == "not_retained"
    assert report["classification_comparison"] == "insufficient_labeled_samples"


def test_overlap_missing_media_and_path_hints_do_not_authorize_classification_or_reads(tmp_path):
    raw = picture()
    secret = tmp_path / "outside.png"
    secret.write_bytes(raw)
    extra = _bytes(45812, str(secret).encode()) + _bytes(45403, b"private text")
    report = successful(run_probe(tmp_path, [sample(raw, 1, "ordinary", extra=extra),
                                           sample(raw, 1, "custom")], {}))
    assert report["classification_comparison"] == "overlap_in_selected_labels"
    assert report["samples"][0]["fields"]["45406"]["observations"][0]["matches"] == []
    assert report["samples"][0]["fields"]["45812"]["observations"][0]["category"] == "path_hint_not_followed"
    assert "private text" not in json.dumps(report)
    assert str(secret) not in json.dumps(report)


def test_duplicate_digest_fields_wrong_wire_and_bad_media_are_explicit(tmp_path):
    raw = b"not an image"
    extra = (_bytes(45406, b"x" * 16) + _bytes(45424, b"private-bad-digest")
             + _scalar(45424, 9) + _scalar(45418, 2))
    report = successful(run_probe(tmp_path, [sample(raw, 999999, "unknown", extra=extra)], {"a": raw}))
    row = report["samples"][0]
    assert len(row["fields"]["45406"]["observations"]) == 2
    assert row["digest_relation"] == "not_comparable"
    assert row["fields"]["45003"]["observations"][0]["category"] == "out_of_range"
    assert row["fields"]["45424"]["observations"][1]["wire_type"] == 0
    assert report["media"][0]["status"] == "invalid"
    assert "private-bad-digest" not in json.dumps(report)


@pytest.mark.parametrize("entry", ["../outside.png", "C:/private.png", "https://example.test/a", "\\\\server\\share\\a"])
def test_unapproved_media_paths_fail_without_exposing_them(tmp_path, entry):
    result = run_probe(tmp_path, [sample(picture(), 0, "ordinary")], {}, entries=[entry])
    assert result.returncode == 2
    assert json.loads(result.stdout) == {"error": "invalid_media_path"}
    assert result.stderr == ""


def test_truncated_blob_and_excessive_sample_count_fail_closed(tmp_path):
    bad = {"message_blob": base64.b64encode(b"\x82").decode(), "pic_index": 0,
           "known_class": "ordinary"}
    result = run_probe(tmp_path, [bad], {})
    assert result.returncode == 2
    assert json.loads(result.stdout) == {"error": "invalid_message_blob"}
    result = run_probe(tmp_path, [sample(picture(), 0, "ordinary")] * 17, {})
    assert result.returncode == 2
    assert json.loads(result.stdout) == {"error": "sample_budget"}


def test_fixed_wire_is_visible_and_missing_class_evidence_prevents_separation_claim(tmp_path):
    raw = picture()
    ordinary = sample(raw, 0, "ordinary")
    custom = sample(raw, 1, "custom")
    # A fixed32 occurrence is present, but production intentionally skips its value.
    # Hand construct fixed32 key using the existing scalar encoder, replacing wire bits.
    key = bytearray(_scalar(45003, 0)[:-1])
    key[0] |= 5
    fixed = _scalar(45002, 2) + bytes(key) + b"ABCD"
    unknown = {"message_blob": base64.b64encode(_bytes(40800, fixed)).decode(),
               "pic_index": 0, "known_class": "ordinary"}
    report = successful(run_probe(tmp_path, [ordinary, custom, unknown], {}))
    assert report["samples"][2]["fields"]["45003"] == {
        "present": True, "observations": [{"wire_type": 5, "category": "unexpected_wire_type"}]}
    assert report["classification_comparison"] == "insufficient_labeled_samples"


def test_duplicate_json_keys_and_oversized_manifest_do_not_produce_partial_reports(tmp_path):
    root = tmp_path / "copies"
    root.mkdir()
    source = tmp_path / "input.json"
    for raw, reason in [('{"samples": [], "samples": []}', "duplicate_json_key"),
                        (" " * (2 * 1024 ** 2 + 1), "file_budget")]:
        source.write_text(raw)
        result = subprocess.run([sys.executable, str(SCRIPT), "--input", str(source),
                                 "--media-root", str(root)], capture_output=True, text=True, timeout=20)
        assert result.returncode == 2
        assert json.loads(result.stdout) == {"error": reason}
        assert result.stderr == ""


def test_only_listed_copies_are_read_and_missing_copy_is_explicit(tmp_path):
    raw = picture()
    report = successful(run_probe(tmp_path, [sample(raw, 0, "ordinary")],
                                  {"unlisted-original": raw}, entries=["missing-copy"]))
    assert report["media"] == [{"candidate": "m1", "status": "missing",
                                "reason": "selected_file_missing"}]
    assert report["samples"][0]["fields"]["45406"]["observations"][0]["matches"] == []


def test_link_to_unapproved_file_is_rejected_before_read(tmp_path):
    target = tmp_path / "unapproved"
    target.write_bytes(picture())
    root = tmp_path / "copies"
    root.mkdir()
    try:
        os.symlink(target, root / "link")
    except OSError:
        pytest.skip("File symlink creation unavailable on this host")
    report = successful(run_probe(tmp_path, [sample(picture(), 0, "ordinary")], {}, entries=["link"]))
    assert report["media"] == [{"candidate": "m1", "status": "unsafe",
                                "reason": "reparse_or_symlink"}]
    assert report["samples"][0]["fields"]["45406"]["observations"][0]["matches"] == []
