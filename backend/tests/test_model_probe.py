"""The local probe must report failures without copying private library inputs."""

import json

from agemorph3d import model_probe


def arguments(monkeypatch, tmp_path, output_dir):
    monkeypatch.setattr(
        "sys.argv",
        [
            "model_probe",
            "--manifest",
            str(tmp_path / "missing.json"),
            "--image",
            str(tmp_path / "private-photo.png"),
            "--output-dir",
            str(output_dir),
        ],
    )


def test_missing_manifest_produces_failure_report(monkeypatch, tmp_path, capsys):
    output = tmp_path / "report"
    arguments(monkeypatch, tmp_path, output)
    assert model_probe.main() == 1
    report = json.loads((output / "report.json").read_text())
    assert report["technical_execution"] == "failed"
    assert report["error_type"] == "ModelAssetError"
    assert report["license_verified"] is False and report["b0_complete"] is False
    assert str(tmp_path) not in json.dumps(report)
    assert "Traceback" not in capsys.readouterr().err


def test_output_directory_failure_is_structured(monkeypatch, tmp_path, capsys):
    output = tmp_path / "existing-file"
    output.write_text("retain this file")
    arguments(monkeypatch, tmp_path, output)
    assert model_probe.main() == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["technical_execution"] == "failed"
    assert str(tmp_path) not in captured.out + captured.err
    assert output.read_text() == "retain this file"


def test_library_failure_preserves_provenance_and_hides_raw_error(monkeypatch, tmp_path, capsys):
    output = tmp_path / "report"
    arguments(monkeypatch, tmp_path, output)

    def failed_probe(_args, report):
        report.update(model_id="checked-model", license_verified=False)
        raise RuntimeError("secret input with private original-photo filename")

    monkeypatch.setattr(model_probe, "probe", failed_probe)
    assert model_probe.main() == 1
    text = (output / "report.json").read_text()
    report = json.loads(text)
    assert report["model_id"] == "checked-model"
    assert report["error_type"] == "RuntimeError"
    assert "secret" not in text and "original-photo" not in text
    assert "secret" not in capsys.readouterr().out


def test_report_write_failure_is_structured(monkeypatch, tmp_path, capsys):
    output = tmp_path / "report"
    output.mkdir()
    (output / "report.json").mkdir()  # Cannot replace this directory with a file.
    arguments(monkeypatch, tmp_path, output)
    assert model_probe.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["error_type"] == "ReportWriteError"
    assert result["technical_execution"] == "failed"
