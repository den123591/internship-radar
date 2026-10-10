from radar.cli import main


def test_cli_ingest_stats_and_match(tmp_path, capsys):
    db = f"sqlite:///{tmp_path / 'cli.db'}"
    assert main(["--db", db, "ingest", "--source", "sample"]) == 0
    assert "новых" in capsys.readouterr().out

    assert main(["--db", db, "stats"]) == 0
    assert '"top_skills"' in capsys.readouterr().out

    resume = tmp_path / "resume.txt"
    resume.write_text("Python, SQL, Git, Docker, FastAPI", encoding="utf-8")
    assert main(["--db", db, "match", str(resume), "--top", "3"]) == 0
    out = capsys.readouterr().out
    assert out.count("https://") == 3


def test_cli_reports_unavailable_source(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("RADAR_HH_TOKEN", raising=False)
    assert main(["--db", f"sqlite:///{tmp_path / 'x.db'}", "ingest", "--source", "hh"]) == 2
    assert "RADAR_HH_TOKEN" in capsys.readouterr().err
