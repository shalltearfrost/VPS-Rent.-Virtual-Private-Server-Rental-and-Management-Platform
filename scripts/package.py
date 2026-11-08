from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    output = ROOT / "outputs" / "vps-rent-alpha.zip"
    output.parent.mkdir(exist_ok=True)
    files = [
        ROOT / name
        for name in (
            "README.md",
            ".gitignore",
            "pyproject.toml",
            "requirements.lock",
            "compose.yaml",
            "alembic.ini",
        )
    ]
    for name in ("app", "migrations", "scripts", "tests", "docs"):
        files.extend(
            path
            for path in (ROOT / name).rglob("*")
            if (path.is_file() and "__pycache__" not in path.parts)
        )
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(ROOT))
    print(f"Packaged {len(files)} source and documentation files.")


if __name__ == "__main__":
    main()
