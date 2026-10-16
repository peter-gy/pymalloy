import maturin
from native_archive import prepare


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    prepare(maturin.get_maturin_pep517_args(config_settings))
    return maturin.build_wheel(wheel_directory, config_settings, metadata_directory)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    prepare(maturin.get_maturin_pep517_args(config_settings))
    return maturin.build_editable(wheel_directory, config_settings, metadata_directory)


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    prepare(maturin.get_maturin_pep517_args(config_settings), download=False)
    return maturin.prepare_metadata_for_build_wheel(metadata_directory, config_settings)


prepare_metadata_for_build_editable = prepare_metadata_for_build_wheel
build_sdist = maturin.build_sdist
get_requires_for_build_wheel = maturin.get_requires_for_build_wheel
get_requires_for_build_editable = maturin.get_requires_for_build_editable
get_requires_for_build_sdist = maturin.get_requires_for_build_sdist
