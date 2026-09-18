import os
import stat
from contextlib import contextmanager

import pytest

from pymalloy import _persistence


def test_write_preserves_line_endings_and_rejects_stale_revisions(tmp_path):
    path = tmp_path / "model.malloy"
    original = "// original\r\n"
    assert _persistence.write_text(path, original) == path
    assert path.read_bytes() == original.encode()

    with pytest.raises(FileExistsError):
        _persistence.write_text(path, "unrelated overwrite")
    with pytest.raises(ValueError, match="changed on disk"):
        _persistence.write_text(path, "stale overwrite", expected="// original\n")
    assert path.read_bytes() == original.encode()

    updated = "// updated\r\n"
    _persistence.write_text(path, updated, expected=original)
    assert path.read_bytes() == updated.encode()
    path.unlink()
    with pytest.raises(ValueError, match="changed on disk"):
        _persistence.write_text(path, original, expected=updated)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions")
@pytest.mark.parametrize("checked", [False, True])
def test_replacement_preserves_existing_permissions(tmp_path, checked):
    path = tmp_path / "model.malloy"
    path.write_text("original")
    path.chmod(0o640)
    _persistence.write_text(
        path, "updated", expected="original" if checked else None, overwrite=True
    )
    assert path.read_text() == "updated"
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


@pytest.mark.parametrize("existing", [False, True])
def test_failed_staging_does_not_publish_partial_content(
    tmp_path, monkeypatch, existing
):
    path = tmp_path / "model.malloy"
    if existing:
        path.write_text("original")
    fdopen = os.fdopen

    @contextmanager
    def interrupted_write(descriptor, mode):
        with fdopen(descriptor, mode) as handle:

            class Writer:
                def write(self, content):
                    handle.write(content[:2])
                    raise OSError("disk full")

            yield Writer()

    monkeypatch.setattr(_persistence.os, "fdopen", interrupted_write)
    with pytest.raises(OSError, match="disk full"):
        _persistence.write_text(path, "replacement", overwrite=existing)
    assert sorted(tmp_path.iterdir()) == ([path] if existing else [])
    if existing:
        assert path.read_text() == "original"


@pytest.mark.parametrize("existing", [False, True])
def test_failed_publication_leaves_destination_unchanged(
    tmp_path, monkeypatch, existing
):
    path = tmp_path / "model.malloy"
    if existing:
        path.write_text("original")

    def fail_publish(source, destination):
        raise OSError("publication failed")

    monkeypatch.setattr(
        _persistence.os, "replace" if existing else "link", fail_publish
    )
    with pytest.raises(OSError, match="publication failed"):
        _persistence.write_text(path, "replacement", overwrite=existing)
    assert sorted(tmp_path.iterdir()) == ([path] if existing else [])
    if existing:
        assert path.read_text() == "original"
