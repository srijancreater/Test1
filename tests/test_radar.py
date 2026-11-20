from datetime import date
from pathlib import Path

import pytest

from tender_radar.classifier import classify
from tender_radar.cli import main
from tender_radar.config import load_config
from tender_radar.models import Tender
from tender_radar.pipeline import Filters, run
from tender_radar.sources._parse import parse_date, parse_value

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = str(ROOT / "data" / "sample_tenders.csv")
TODAY = date(2026, 11, 20)


@pytest.fixture(scope="module")
def config():
    return load_config()


def test_all_ten_target_categories_configured(config):
    assert set(config.categories) == {
        "genai", "chatbot", "automation", "analytics", "ocr",
        "surveillance", "software", "poc", "smartcity", "modernization",
    }


@pytest.mark.parametrize("title,expected", [
    ("Generative AI platform using large language models", "genai"),
    ("Multilingual chatbot and voice bot for citizens", "chatbot"),
    ("Robotic process automation for file tracking", "automation"),
    ("Real-time dashboard and business intelligence", "analytics"),
    ("Optical character recognition of land records", "ocr"),
    ("AI video analytics on CCTV with ANPR", "surveillance"),
    ("Mobile application development with AI integration", "software"),
    ("Proof of concept pilot for crop advisory", "poc"),
    ("Integrated command and control centre for smart city", "smartcity"),
    ("Legacy modernization and cloud migration", "modernization"),
])
def test_each_category_detected(config, title, expected):
    t = classify(Tender(id="x", title=title), config)
    assert t.primary_category == expected


def test_whole_word_matching(config):
    # "ai" must not match inside "maintenance" / "repair"
    t = classify(Tender(id="x", title="Maintenance and repair of chairs"), config)
    assert t.categories == {}


def test_global_exclude_flags_tender(config):
    t = classify(Tender(id="x", title="Construction of building with CCTV surveillance"), config)
    assert "excluded" in t.flags


def test_pipeline_on_sample(config):
    results = run([SAMPLE], config, today=TODAY)
    ids = [t.id for t in results]
    for noise in ("DEMO-011", "DEMO-012", "DEMO-013", "DEMO-019"):
        assert noise not in ids
    assert "DEMO-017" not in ids                      # expired
    assert results == sorted(results, key=lambda t: -t.score)
    assert len(results) >= 12


def test_category_filter(config):
    results = run([SAMPLE], config, Filters(categories=["poc"]), today=TODAY)
    assert results and all("poc" in t.categories for t in results)


def test_urgent_flag(config):
    results = run([SAMPLE], config, today=TODAY)
    urgent = {t.id for t in results if "urgent" in t.flags}
    assert "DEMO-002" in urgent and "DEMO-009" not in urgent


@pytest.mark.parametrize("raw,value", [
    ("4.5 Cr", 4.5e7), ("85 lakh", 8.5e6), ("45,00,000", 4.5e6), ("1.2 million", 1.2e6), ("", None),
])
def test_parse_value(raw, value):
    assert parse_value(raw) == value


@pytest.mark.parametrize("raw", ["2026-12-15", "15-12-2026", "15/12/2026", "15-Dec-2026",
                                 "15 Dec 2026 10:00 AM", "Tue, 15 Dec 2026 10:00:00 +0530"])
def test_parse_date(raw):
    assert parse_date(raw) == date(2026, 12, 15)


def test_rss_and_json_sources(tmp_path, config):
    rss = tmp_path / "feed.xml"
    rss.write_text("""<rss><channel><item><title>AI chatbot for municipal grievance</title>
        <description>&lt;p&gt;Conversational AI&lt;/p&gt;</description><link>https://example.org/1</link>
        <pubDate>Mon, 16 Nov 2026 09:00:00 +0530</pubDate></item></channel></rss>""")
    js = tmp_path / "t.json"
    js.write_text('{"tenders": [{"id": "J1", "title": "OCR of records", "deadline": "2026-12-31"}]}')
    results = run([str(rss), str(js)], config, Filters(min_score=0.1), today=TODAY)
    assert {t.primary_category for t in results} == {"chatbot", "ocr"}


def test_cli_writes_reports(tmp_path, capsys):
    html, csv_ = tmp_path / "r.html", tmp_path / "r.csv"
    assert main(["scan", SAMPLE, "--today", "2026-11-20", "--html", str(html), "--csv", str(csv_)]) == 0
    assert "Tender Radar" in html.read_text()
    assert csv_.read_text().count("\n") > 10
    assert main(["explain", SAMPLE, "--id", "DEMO-006"]) == 0
    assert "surveillance" in capsys.readouterr().out.lower()
