from pathlib import Path

from line_balancer.main import resolve_input_path


def test_resolve_input_path_uses_sample_file_when_missing():
    resolved = resolve_input_path(None)
    assert Path(resolved).exists()
    assert Path(resolved).name == "sample_operations.csv"


def test_resolve_input_path_keeps_explicit_value():
    explicit = "custom.csv"
    assert resolve_input_path(explicit) == explicit
