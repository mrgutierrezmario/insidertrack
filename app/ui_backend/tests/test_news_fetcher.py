"""services.news_fetcher — the keyless Google News path (no network)."""

from services import news_fetcher as nf

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>
<item><title>Nvidia hits record</title><link>https://a/1</link><pubDate>Fri, 19 Sep 2026 14:02:00 GMT</pubDate><source url="https://r">Reuters</source></item>
<item><title>Chips rally</title><link>https://a/2</link><pubDate>Thu, 18 Sep 2026 09:00:00 GMT</pubDate><source url="https://b">Bloomberg</source></item>
<item><title>Dup</title><link>https://a/1</link><pubDate>Thu, 18 Sep 2026 08:00:00 GMT</pubDate></item>
</channel></rss>"""


class _Resp:
    status_code = 200
    text = RSS


class _Client:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def get(self, url, params=None): return _Resp()


def test_google_news_shapes_items(monkeypatch):
    monkeypatch.setattr(nf.httpx, "Client", _Client)
    items = nf._google_news(["NVDA"], limit=10)
    assert [i["title"] for i in items] == ["Nvidia hits record", "Chips rally"]   # dedup by link, newest first
    first = items[0]
    assert first["source"] == "Reuters" and first["provider"] == "google-news"
    assert first["overall_label"] == "Neutral" and first["sentiment_value"] == 50 and first["sentiment_source"] == "keywords"
    assert items[1]["overall_label"] == "Somewhat-Bullish"                          # "rally"
    assert first["published"].startswith("2026-09-19T14:02")
    assert first["tickers"] == ["NVDA"]


def test_get_news_uses_google_without_a_key(monkeypatch):
    monkeypatch.setattr(nf.httpx, "Client", _Client)
    monkeypatch.setattr(nf.settings, "alpha_vantage_key", "")
    nf._cache.clear()
    assert nf.get_news(["NVDA"])[0]["provider"] == "google-news"


class TestHeadlineSentiment:
    def test_keyword_labels(self):
        from services.news_fetcher import headline_sentiment as hs
        assert hs("Nvidia shares surge after earnings beat") == "Somewhat-Bullish"
        assert hs("Boeing plunges as FAA opens probe into 737 recall") == "Somewhat-Bearish"
        assert hs("Apple to hold event on September 9") == "Neutral"
        assert hs("Stock jumps then falls back") == "Neutral"                 # tie
        assert hs("") == "Neutral"
