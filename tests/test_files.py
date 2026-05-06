from council.files import read_text_snapshot


def test_read_text_snapshot_hashes_content(tmp_path):
    path = tmp_path / "sample.md"
    path.write_text("hello", encoding="utf-8")

    snapshot = read_text_snapshot(path)

    assert snapshot.content == "hello"
    assert len(snapshot.content_hash) == 64
    assert snapshot.path.endswith("sample.md")

