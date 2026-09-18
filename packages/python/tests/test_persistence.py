import stat

import pytest

import pymalloy as pm


def test_saving_uses_normal_file_permissions_and_preserves_existing_mode(tmp_path):
    reference = tmp_path / "reference.txt"
    reference.write_text("ordinary file")
    path = tmp_path / "model.malloy"
    draft = pm.draft().define(values=pm.sql("SELECT 42 value"))
    draft.save(path)
    assert stat.S_IMODE(path.stat().st_mode) == stat.S_IMODE(reference.stat().st_mode)
    path.chmod(0o640)
    draft.save(path, overwrite=True)
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    with pytest.raises(FileExistsError):
        draft.save(path)
    assert path.read_text() == draft.text
