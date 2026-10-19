"""Manifest settings stay explicit; environment mistakes fail during setup."""

from pathlib import Path

import pytest

from agemorph3d.config import DEFAULT_ALLOWED_ORIGINS, Settings


def test_no_manifest_is_the_default() -> None:
    assert Settings().detector_manifest is None
    assert Settings().reconstructor_manifest is None


def test_manifest_environment_combines_with_default_and_explicit_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGEMORPH_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv("AGEMORPH_DETECTOR_MANIFEST", "data/models/detector.json")
    monkeypatch.setenv("AGEMORPH_RECONSTRUCTOR_MANIFEST", "data/models/reconstructor.json")
    settings = Settings.from_env()
    assert settings.allowed_origins == DEFAULT_ALLOWED_ORIGINS
    assert settings.detector_manifest == Path("data/models/detector.json")
    assert settings.reconstructor_manifest == Path("data/models/reconstructor.json")
    monkeypatch.setenv("AGEMORPH_ALLOWED_ORIGINS", "http://localhost:5173")
    assert Settings.from_env().allowed_origins == ("http://localhost:5173",)
    assert Settings.from_env().detector_manifest == settings.detector_manifest


@pytest.mark.parametrize("name", ["detector_manifest", "reconstructor_manifest"])
@pytest.mark.parametrize("value", ["", " ", "."])
def test_manifest_environment_rejects_empty_paths(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(f"AGEMORPH_{name.upper()}", value)
    with pytest.raises(ValueError, match="manifest"):
        Settings.from_env()


@pytest.mark.parametrize("name", ["detector_manifest", "reconstructor_manifest"])
@pytest.mark.parametrize("value", ["", "model.json", True, Path(".")])
def test_explicit_manifest_settings_require_nonempty_paths(name: str, value: object) -> None:
    with pytest.raises(ValueError, match="manifest"):
        Settings(**{name: value})
