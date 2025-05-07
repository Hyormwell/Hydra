from pathlib import Path
import pytest
from hydra_reposter.utils.csv_loader import load_targets_from_csv


@pytest.fixture()
def tmp_csv(tmp_path: Path):
    csv = tmp_path / "targets.csv"
    csv.write_text("""
        # comment
        @chan1
        @chan2,ignored
        https://t.me/chat3
    """, encoding="utf-8")
    return csv


def test_load_ok(tmp_csv: Path):
    assert load_targets_from_csv(tmp_csv) == [
        "@chan1", "@chan2", "https://t.me/chat3"
    ]


def test_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_targets_from_csv(tmp_path / "absent.csv")


def test_empty(tmp_path: Path):
    empty = (tmp_path / "empty.csv")
    empty.touch()
    with pytest.raises(ValueError):
        load_targets_from_csv(empty)