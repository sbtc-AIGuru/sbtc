import re

import pytest
import requests

from Scripts.Kaggle import download_vibiomir_snapshot as downloader


class Response:
    def __init__(self, data, start, end, *, cut=False, status=206, wrong_range=False):
        self.status_code = status
        self.headers = {"Content-Range": f"bytes {start + int(wrong_range)}-{end}/{len(data)}"}
        self.data = data[start:end+1]
        self.cut = cut

    def __enter__(self): return self
    def __exit__(self, *args): pass

    def iter_content(self, chunk_size):
        if self.cut:
            yield self.data[:2]
            raise requests.exceptions.ChunkedEncodingError("connection dropped")
        yield self.data


class Session:
    def __init__(self, data, **first_options):
        self.data = data
        self.options = first_options
        self.calls = []

    def get(self, url, headers, **kwargs):
        self.calls.append(headers["Range"])
        start, end = map(int, re.fullmatch(r"bytes=(\d+)-(\d+)", headers["Range"]).groups())
        options = self.options if len(self.calls) == 1 else {}
        return Response(self.data, start, end, **options)


def test_disconnect_preserves_bytes_and_resumes_from_written_offset(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader.time, "sleep", lambda _: None)
    data = b"abcdefgh"
    partial = tmp_path / "snapshot.partial"
    session = Session(data, cut=True)
    downloader.stream_ranges(lambda: "signed-url", partial, len(data), chunk_bytes=4, session=session)
    assert partial.read_bytes() == data
    assert session.calls == ["bytes=0-3", "bytes=2-5", "bytes=6-7"]


def test_resume_from_existing_partial(tmp_path):
    partial = tmp_path / "snapshot.partial"
    partial.write_bytes(b"abc")
    session = Session(b"abcdefgh")
    downloader.stream_ranges(lambda: "signed-url", partial, 8, chunk_bytes=4, session=session)
    assert session.calls == ["bytes=3-6", "bytes=7-7"]
    assert partial.read_bytes() == b"abcdefgh"


@pytest.mark.parametrize("options", [{"status": 200}, {"wrong_range": True}])
def test_refuses_ignored_or_mismatched_range_without_appending(tmp_path, options):
    partial = tmp_path / "snapshot.partial"
    partial.write_bytes(b"ab")
    with pytest.raises(RuntimeError):
        downloader.stream_ranges(lambda: "signed-url", partial, 8, chunk_bytes=4,
                                 session=Session(b"abcdefgh", **options))
    assert partial.read_bytes() == b"ab"


def test_retry_limit_keeps_partial_for_next_run(tmp_path):
    partial = tmp_path / "snapshot.partial"
    with pytest.raises(RuntimeError, match="bytes preserved"):
        downloader.stream_ranges(lambda: "signed-url", partial, 8, chunk_bytes=4,
                                 max_failures=0, session=Session(b"abcdefgh", cut=True))
    assert partial.read_bytes() == b"ab"


def test_expired_signed_url_is_refreshed_without_discarding_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader.time, "sleep", lambda _: None)
    calls = []
    def provider(refresh=False):
        calls.append(refresh)
        return "signed-url"
    partial = tmp_path / "snapshot.partial"
    partial.write_bytes(b"ab")
    session = Session(b"abcdefgh", status=403)
    downloader.stream_ranges(provider, partial, 8, chunk_bytes=4, session=session)
    assert True in calls
    assert session.calls[:2] == ["bytes=2-5", "bytes=2-5"]
    assert partial.read_bytes() == b"abcdefgh"
