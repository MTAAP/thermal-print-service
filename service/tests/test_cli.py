import argparse

from printer.cli import main as cli


class FakeResponse:
    status = 202

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b'{"id":"job1"}'


def test_cmd_test_print_posts_test_endpoint(monkeypatch, capsys):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(cli.request, "urlopen", fake_urlopen)

    code = cli.cmd_test_print(argparse.Namespace(url="http://printer.local:8000", timeout=3.5))

    assert code == 0
    assert seen == {
        "url": "http://printer.local:8000/test",
        "method": "POST",
        "timeout": 3.5,
    }
    assert "202" in capsys.readouterr().out
