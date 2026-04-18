from scripts import validate_docs_references as docs_validate


def test_validate_doc_detects_missing_markdown_link(tmp_path, monkeypatch):
    monkeypatch.setattr(docs_validate, "WORKDIR", tmp_path)
    doc = tmp_path / "README.md"
    doc.write_text("[Missing](missing-file.md)\n", encoding="utf-8")

    row = docs_validate._validate_doc(doc)
    assert "missing-file.md" in row["missing_links"]


def test_validate_doc_detects_missing_docker_compose_file(tmp_path, monkeypatch):
    monkeypatch.setattr(docs_validate, "WORKDIR", tmp_path)
    doc = tmp_path / "README.md"
    doc.write_text("Use `docker compose -f docker-compose.yml up`.\n", encoding="utf-8")

    row = docs_validate._validate_doc(doc)
    assert "docker-compose.yml" in row["missing_compose_files"]


def test_validate_doc_passes_when_refs_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(docs_validate, "WORKDIR", tmp_path)
    target = tmp_path / "exists.md"
    target.write_text("# ok\n", encoding="utf-8")
    compose = tmp_path / "docker-compose.local.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    doc = tmp_path / "README.md"
    doc.write_text(
        "[Existing](exists.md)\nUse `docker-compose.local.yml`.\n",
        encoding="utf-8",
    )

    row = docs_validate._validate_doc(doc)
    assert row["missing_links"] == []
    assert row["missing_compose_files"] == []
