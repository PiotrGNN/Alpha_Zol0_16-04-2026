import argparse
import json
import re
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
DOC_DEFAULTS = ("README.md", "TODO.md", "AUDIT_STATUS.md")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
DOCKER_COMPOSE_NAME_RE = re.compile(r"docker-compose[^\s`\"']*\.yml", re.IGNORECASE)


def _normalize_local_ref(ref: str) -> str:
    return str(ref or "").strip()


def _is_external_ref(ref: str) -> bool:
    txt = ref.lower()
    return (
        txt.startswith("http://")
        or txt.startswith("https://")
        or txt.startswith("mailto:")
        or txt.startswith("#")
    )


def _validate_doc(doc_path: Path) -> dict:
    text = doc_path.read_text(encoding="utf-8")
    missing_links = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        raw_ref = _normalize_local_ref(match.group(1))
        if not raw_ref or _is_external_ref(raw_ref):
            continue
        clean_ref = raw_ref.split("#", 1)[0].strip()
        if not clean_ref:
            continue
        ref_path = (doc_path.parent / clean_ref).resolve()
        if not ref_path.exists():
            missing_links.append(clean_ref)

    missing_compose_files = []
    for compose_name in sorted(set(DOCKER_COMPOSE_NAME_RE.findall(text))):
        if "*" in compose_name or "?" in compose_name:
            continue
        if not (WORKDIR / compose_name).exists():
            missing_compose_files.append(compose_name)

    return {
        "doc_path": str(doc_path.resolve()),
        "missing_links": sorted(set(missing_links)),
        "missing_compose_files": sorted(set(missing_compose_files)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate local markdown references and docker-compose filenames in docs."
    )
    parser.add_argument(
        "--docs",
        nargs="*",
        default=list(DOC_DEFAULTS),
        help="Doc paths relative to repository root.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero when any missing reference is found.",
    )
    args = parser.parse_args(argv)

    rows = []
    for rel in args.docs:
        doc_path = (WORKDIR / rel).resolve()
        if not doc_path.exists():
            rows.append(
                {
                    "doc_path": str(doc_path),
                    "missing_links": [f"document_missing:{rel}"],
                    "missing_compose_files": [],
                }
            )
            continue
        rows.append(_validate_doc(doc_path))

    total_missing = sum(
        len(row["missing_links"]) + len(row["missing_compose_files"]) for row in rows
    )
    payload = {
        "repo_root": str(WORKDIR),
        "checked_docs": len(rows),
        "total_missing_refs": total_missing,
        "results": rows,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    if args.strict and total_missing > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
