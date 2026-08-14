import pytest

from deckifyr.resolvers import BuildContext, TableResolver
from deckifyr.schema.errors import ContentValidationError


def test_supports_csv_and_parquet_only():
    resolver = TableResolver()
    assert resolver.supports("data.csv") is True
    assert resolver.supports("data.parquet") is True
    assert resolver.supports("data.xlsx") is False
    assert resolver.supports("{rpfy}:data.csv") is False


def test_resolves_csv_into_headers_and_rows(tmp_path):
    (tmp_path / "data.csv").write_text("name,score\nAda,10\nGrace,9\n")
    resolved = TableResolver().resolve("data.csv", BuildContext(project_root=str(tmp_path)))
    assert resolved.value.headers == ["name", "score"]
    assert resolved.value.rows == [["Ada", "10"], ["Grace", "9"]]


def test_resolves_parquet_into_headers_and_rows(tmp_path):
    pa = pytest.importorskip("pyarrow", reason="optional Parquet dependency not installed")
    pq = pytest.importorskip("pyarrow.parquet")

    table = pa.table({"name": ["Ada", "Grace"], "score": [10, 9]})
    pq.write_table(table, tmp_path / "data.parquet")

    resolved = TableResolver().resolve("data.parquet", BuildContext(project_root=str(tmp_path)))
    assert resolved.value.headers == ["name", "score"]
    assert resolved.value.rows == [["Ada", "10"], ["Grace", "9"]]


def test_empty_csv_raises(tmp_path):
    (tmp_path / "data.csv").write_text("")
    with pytest.raises(ContentValidationError):
        TableResolver().resolve("data.csv", BuildContext(project_root=str(tmp_path)))


def test_unsupported_extension_raises(tmp_path):
    (tmp_path / "data.txt").write_text("a,b\n1,2\n")
    with pytest.raises(ContentValidationError):
        TableResolver().resolve("data.txt", BuildContext(project_root=str(tmp_path)))


def test_csv_row_with_too_many_columns_raises(tmp_path):
    (tmp_path / "data.csv").write_text("a,b\n1,2,3\n")
    with pytest.raises(ContentValidationError):
        TableResolver().resolve("data.csv", BuildContext(project_root=str(tmp_path)))


def test_path_traversal_rejected(tmp_path):
    with pytest.raises(ContentValidationError):
        TableResolver().resolve("../outside.csv", BuildContext(project_root=str(tmp_path)))
