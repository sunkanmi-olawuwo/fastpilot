"""
Final Capstone Pre-Submission Check
=====================================

Run this before submitting to catch structural issues, bloat, and secrets.

Usage (from your capstone repo root):
    uv run python final-submission/prequalify.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Resolve final-submission/ directory (script lives inside it)
WEEK_DIR = Path(__file__).resolve().parent
REPO_ROOT = WEEK_DIR.parent

# Expected filename: firstname_lastname_final_submission.txt
SUBMISSION_FILENAME_PATTERN = r"^[a-z]+(_[a-z]+)+_final_submission\.txt$"

REQUIRED_FILES = {
    "submission.md": "Your master submission document",
    "video-transcript.md": "Written transcript of your Loom video",
    "docs/scoping.md": "Problem scoping (Week 1)",
    "docs/chunking-strategy.md": "Chunking decisions (Week 2)",
    "docs/retrieval-strategy.md": "Retrieval decisions (Week 3)",
    "docs/production-decisions.md": "Production service decisions (Week 5)",
    "docs/iteration-log.md": "Running iteration log across all weeks",
    ".gitingestignore": "Gitingest ignore rules",
}

OPTIONAL_FILES = {
    "docs/evaluation-strategy.md": "Evaluation framework (Week 4) — optional, counts toward bonus",
    "docs/augmentation-decisions.md": "Augmentation decisions (Week 6) — optional, counts toward bonus",
}

SUBMISSION_REQUIRED_SECTIONS = [
    "Student Name",
    "Product Name",
    "Project Title",
    "Demo Video",
    "Problem Statement",
    "Data Overview",
    "System Architecture",
    "Chunking Strategy",
    "Retrieval Pipeline",
    "Production System",
    "Results",
    "Self-Assessment",
]

TRANSCRIPT_REQUIRED_SECTIONS = [
    "Product Name",
    "Problem Setup",
    "System Design",
    "Live Demo",
]

MAX_SUBMISSION_BYTES = 1_000_000  # 1MB
MIN_SUBMISSION_BYTES = 5_000      # 5KB
MAX_FILE_COUNT = 80               # Higher than weekly submissions — full project
MAX_SINGLE_FILE_LINES = 2000

# Loom URL pattern
LOOM_URL_PATTERN = r"https?://(?:www\.)?loom\.com/share/[a-zA-Z0-9]+"

# Patterns that indicate leaked secrets
SECRET_PATTERNS = [
    (r"sk-[a-zA-Z0-9]{20,}", "OpenAI API key"),
    (r"ghp_[a-zA-Z0-9]{36}", "GitHub PAT"),
    (r"ghu_[a-zA-Z0-9]{36}", "GitHub user token"),
    (r"QDRANT_API_KEY\s*=\s*(?!os\.|Secret|None|getenv|environ|\"|\')[A-Za-z0-9_\-]{8,}", "Qdrant API key"),
    (r"GOOGLE_API_KEY\s*=\s*(?!os\.|Secret|None|getenv|environ|\"|\')[A-Za-z0-9_\-]{8,}", "Google API key"),
    (r"ANTHROPIC_API_KEY\s*=\s*(?!os\.|Secret|None|getenv|environ|\"|\')[A-Za-z0-9_\-]{8,}", "Anthropic API key"),
    (r"VOYAGE_API_KEY\s*=\s*(?!os\.|Secret|None|getenv|environ|\"|\')[A-Za-z0-9_\-]{8,}", "Voyage API key"),
    (r"TAVILY_API_KEY\s*=\s*(?!os\.|Secret|None|getenv|environ|\"|\')[A-Za-z0-9_\-]{8,}", "Tavily API key"),
    (r"Bearer\s+[a-zA-Z0-9\-_.]{20,}", "Bearer token"),
    (r"password\s*=\s*['\"][^'\"]{8,}['\"]", "Hardcoded password"),
]

# Patterns indicating raw data or large artifacts leaked into submission
DATA_BLOAT_PATTERNS = [
    (r"^FILE:\s+.*data/raw/", "data/raw/ files included — check .gitingestignore"),
    (r"^FILE:\s+.*data/processed/", "data/processed/ files included — check .gitingestignore"),
    (r"^FILE:\s+.*\.env$", ".env file included — secrets may be exposed"),
    (r"^FILE:\s+.*\.csv$", "CSV file included — should be in .gitingestignore"),
    (r"^FILE:\s+.*\.parquet$", "Parquet file included — should be in .gitingestignore"),
    (r"^FILE:\s+.*\.npy$", "NumPy file included — should be in .gitingestignore"),
    (r"^FILE:\s+.*rag_results/.*\.json$", "RAG results JSON included — should be in .gitingestignore (too large)"),
    (r"^FILE:\s+.*archive/", "Archive files included — should be in .gitingestignore"),
    (r"^FILE:\s+.*prequalify\.py$", "Prequalify script included — add to .gitingestignore"),
    (r"^FILE:\s+.*submission_guidelines\.md$", "Submission guidelines included — add to .gitingestignore"),
    (r"^FILE:\s+.*data_preparation/outputs/", "data_preparation/outputs/ included — check .gitingestignore"),
]

# Items that MUST be in .gitingestignore
REQUIRED_IGNORE_ENTRIES = [
    "archive/",
    "rag_results/",
]


def check_file_exists(rel_path: str, description: str) -> bool:
    path = WEEK_DIR / rel_path
    if path.exists():
        print(f"  PASS  {rel_path}")
        return True
    else:
        print(f"  FAIL  {rel_path} — {description}")
        return False


def check_optional_file(rel_path: str, description: str) -> bool:
    path = WEEK_DIR / rel_path
    if path.exists():
        print(f"  PASS  {rel_path} (optional — present)")
        return True
    else:
        print(f"  INFO  {rel_path} — not present (optional)")
        return False


def check_has_scripts() -> bool:
    scripts_dir = WEEK_DIR / "scripts"
    app_dir = WEEK_DIR / "app"

    scripts_py = list(scripts_dir.glob("**/*.py")) if scripts_dir.exists() else []
    app_py = list(app_dir.glob("**/*.py")) if app_dir.exists() else []

    total = len(scripts_py) + len(app_py)

    if total == 0:
        print(f"  FAIL  No Python files found in scripts/ or app/")
        return False

    parts = []
    if scripts_py:
        parts.append(f"{len(scripts_py)} in scripts/")
    if app_py:
        parts.append(f"{len(app_py)} in app/")
    print(f"  PASS  {total} Python file(s) ({', '.join(parts)})")
    return True


def check_sections(file_path: Path, required_sections: list[str], label: str) -> tuple[bool, list[str]]:
    if not file_path.exists():
        return False, required_sections

    content = file_path.read_text()
    missing = []
    for section in required_sections:
        pattern = rf"(^#+\s*{re.escape(section)}|^\*\*{re.escape(section)}\*\*)"
        if not re.search(pattern, content, re.MULTILINE | re.IGNORECASE):
            if section.lower() not in content.lower():
                missing.append(section)

    if missing:
        print(f"  FAIL  {label} — missing sections: {', '.join(missing)}")
        return False, missing
    else:
        print(f"  PASS  {label} — all required sections present")
        return True, []


def check_student_names() -> tuple[bool, list[str]]:
    submission_path = WEEK_DIR / "submission.md"
    if not submission_path.exists():
        return False, []

    content = submission_path.read_text()

    match = re.search(
        r"##\s*Student\s*Name(?:\(s\)|s)?\s*\n+(.*?)(?=\n##|\Z)",
        content,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        print(f"  FAIL  Student Name section not found in submission.md")
        return False, []

    name_block = match.group(1).strip()
    if not name_block or name_block.startswith("["):
        print(f"  FAIL  Student Name is empty or still a placeholder")
        return False, []

    names = []
    for line in name_block.splitlines():
        line = line.strip().lstrip("- ").lstrip("* ").strip()
        if line and not line.startswith("["):
            for name in line.split(","):
                name = name.strip()
                if name:
                    names.append(name)

    if not names:
        print(f"  FAIL  No student names found in submission.md")
        return False, []

    incomplete = [n for n in names if len(n.split()) < 2]
    if incomplete:
        print(f"  FAIL  Each student must have full name (first + last): {', '.join(incomplete)}")
        return False, names

    print(f"  PASS  Student name(s): {', '.join(names)}")
    return True, names


def check_product_name() -> bool:
    submission_path = WEEK_DIR / "submission.md"
    if not submission_path.exists():
        return False

    content = submission_path.read_text()

    match = re.search(
        r"##\s*Product\s*Name\s*\n+(.*?)(?=\n##|\Z)",
        content,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        print(f"  FAIL  Product Name section not found in submission.md")
        return False

    name = match.group(1).strip()
    if not name or name.startswith("["):
        print(f"  FAIL  Product Name is empty or still a placeholder")
        return False

    word_count = len(name.split())
    if word_count > 5:
        print(f"  WARN  Product Name is {word_count} words — should be 2-3 words (e.g., 'DocPilot', 'CodeNav')")
        return False

    print(f"  PASS  Product Name: {name}")
    return True


def check_loom_link() -> bool:
    submission_path = WEEK_DIR / "submission.md"
    if not submission_path.exists():
        return False

    content = submission_path.read_text()

    loom_match = re.search(LOOM_URL_PATTERN, content)
    if loom_match:
        print(f"  PASS  Loom link found: {loom_match.group(0)}")
        return True

    # Check for any URL that might be a video link (YouTube, etc.)
    any_url = re.search(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be|loom\.com)/\S+", content)
    if any_url:
        print(f"  WARN  Video link found but not a Loom URL: {any_url.group(0)}")
        print(f"        Loom is recommended. If using another platform, ensure the link is accessible.")
        return True

    print(f"  FAIL  No video link found in submission.md")
    print(f"        Record a Loom video (< 3 min) and paste the share link under 'Demo Video'")
    return False


def check_video_transcript() -> bool:
    transcript_path = WEEK_DIR / "video-transcript.md"
    if not transcript_path.exists():
        print(f"  FAIL  video-transcript.md — file not found")
        return False

    content = transcript_path.read_text()
    if len(content.strip()) < 200:
        print(f"  WARN  video-transcript.md — file seems too short ({len(content)} chars)")
        return False

    passed, missing = check_sections(
        transcript_path,
        TRANSCRIPT_REQUIRED_SECTIONS,
        "video-transcript.md",
    )
    return passed


def check_submission_not_template() -> bool:
    submission_path = WEEK_DIR / "submission.md"
    if not submission_path.exists():
        return False

    content = submission_path.read_text()
    template_markers = [
        "[Full name",
        "[2-3 word name",
        "[One-line description",
        "[Loom link here",
        "[Your problem statement from scoping.md",
        "[X documents",
    ]

    unfilled = [m for m in template_markers if m in content]
    if unfilled:
        print(f"  WARN  submission.md — still has template placeholders: {unfilled[0]}...")
        return False
    else:
        print(f"  PASS  submission.md — no template placeholders found")
        return True


def check_gitingestignore_entries() -> bool:
    ignore_path = WEEK_DIR / ".gitingestignore"
    if not ignore_path.exists():
        return False

    content = ignore_path.read_text()
    missing = []
    for entry in REQUIRED_IGNORE_ENTRIES:
        if entry not in content:
            missing.append(entry)

    if missing:
        print(f"  WARN  .gitingestignore — missing recommended entries: {', '.join(missing)}")
        return False
    else:
        print(f"  PASS  .gitingestignore — critical exclusions present")
        return True


def find_submission_txt() -> Path | None:
    candidates = list(REPO_ROOT.glob("*_final_submission.txt"))
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        print(f"  FAIL  Multiple submission files found: {[c.name for c in candidates]}")
        return None
    return None


def check_submission_filename(names: list[str]) -> tuple[bool, Path | None]:
    txt_path = find_submission_txt()

    if txt_path is None:
        print(f"  FAIL  No submission .txt found in repo root")
        print(f"        Expected: firstname_lastname_final_submission.txt")
        print(f"        Run: uv run gitingest final-submission/ -o <name>_final_submission.txt")
        return False, None

    filename = txt_path.name

    if re.match(SUBMISSION_FILENAME_PATTERN, filename):
        print(f"  PASS  {filename} — naming convention correct")
        return True, txt_path

    print(f"  WARN  {filename} — does not match expected pattern")
    print(f"        Expected: firstname_lastname_final_submission.txt")
    return False, txt_path


def check_submission_size(txt_path: Path) -> bool:
    size_bytes = txt_path.stat().st_size
    size_kb = size_bytes / 1024
    size_mb = size_bytes / (1024 * 1024)

    if size_bytes > MAX_SUBMISSION_BYTES:
        print(f"  FAIL  {txt_path.name} — {size_mb:.1f}MB (must be under 1MB). Check .gitingestignore.")
        return False
    elif size_bytes < MIN_SUBMISSION_BYTES:
        print(f"  WARN  {txt_path.name} — {size_kb:.0f}KB (suspiciously small, are your files empty?)")
        return False
    else:
        print(f"  PASS  {txt_path.name} — {size_kb:.0f}KB")
        return True


def check_file_count(txt_path: Path) -> bool:
    content = txt_path.read_text()
    file_headers = re.findall(r"^FILE:\s+", content, re.MULTILINE)
    count = len(file_headers)

    if count > MAX_FILE_COUNT:
        print(f"  FAIL  {count} files in submission (max {MAX_FILE_COUNT}) — likely includes data files")
        return False
    elif count == 0:
        print(f"  FAIL  No files found in submission .txt — gitingest may have failed")
        return False
    else:
        print(f"  PASS  {count} files in submission")
        return True


def check_required_files_in_txt(txt_path: Path) -> bool:
    content = txt_path.read_text()

    required_in_txt = [
        "submission.md",
        "video-transcript.md",
        "scoping.md",
        "chunking-strategy.md",
        "retrieval-strategy.md",
        "production-decisions.md",
        "iteration-log.md",
    ]

    missing = []
    for filename in required_in_txt:
        if filename not in content:
            missing.append(filename)

    if missing:
        print(f"  FAIL  Required files missing from submission .txt: {', '.join(missing)}")
        return False
    else:
        print(f"  PASS  All required files found in submission .txt")
        return True


def check_no_secrets(txt_path: Path) -> bool:
    content = txt_path.read_text()
    found = []

    for pattern, label in SECRET_PATTERNS:
        matches = re.findall(pattern, content)
        if matches:
            found.append(f"{label} ({len(matches)} match{'es' if len(matches) > 1 else ''})")

    if found:
        print(f"  FAIL  Possible secrets detected:")
        for f in found:
            print(f"        - {f}")
        return False
    else:
        print(f"  PASS  No secrets detected")
        return True


def check_no_data_bloat(txt_path: Path) -> bool:
    content = txt_path.read_text()
    found = []

    for pattern, label in DATA_BLOAT_PATTERNS:
        if re.search(pattern, content, re.MULTILINE):
            found.append(label)

    if found:
        print(f"  FAIL  Bloat detected in submission:")
        for f in found:
            print(f"        - {f}")
        return False
    else:
        print(f"  PASS  No bloat detected")
        return True


def check_large_files(txt_path: Path) -> bool:
    content = txt_path.read_text()
    file_sections = re.split(r"^={48}\nFILE:\s+(.+)\n={48}$", content, flags=re.MULTILINE)

    large_files = []
    for i in range(1, len(file_sections) - 1, 2):
        filename = file_sections[i]
        file_content = file_sections[i + 1]
        line_count = file_content.count("\n")
        if line_count > MAX_SINGLE_FILE_LINES:
            large_files.append((filename, line_count))

    if large_files:
        print(f"  WARN  Large files detected (over {MAX_SINGLE_FILE_LINES} lines):")
        for name, lines in large_files:
            print(f"        - {name} ({lines} lines)")
        return False
    else:
        print(f"  PASS  No oversized files")
        return True


def check_no_binary(txt_path: Path) -> bool:
    content = txt_path.read_text(errors="replace")

    base64_blobs = re.findall(r"[A-Za-z0-9+/=]{200,}", content)
    suspicious = [b for b in base64_blobs if len(b) > 500]
    has_binary_marker = "[Binary file]" in content

    issues = []
    if suspicious:
        issues.append(f"{len(suspicious)} base64/binary blob(s) detected")
    if has_binary_marker:
        issues.append("Binary file markers found — binary files should not be in submission")

    if issues:
        print(f"  WARN  Possible binary content:")
        for issue in issues:
            print(f"        - {issue}")
        return False
    else:
        print(f"  PASS  No binary content detected")
        return True


def main():
    print("=" * 60)
    print("  Final Capstone — Pre-Submission Check")
    print("=" * 60)
    print(f"\nChecking: {WEEK_DIR}\n")

    all_passed = True
    warnings = False

    # 1. Required files
    print("Required files:")
    for rel_path, description in REQUIRED_FILES.items():
        if not check_file_exists(rel_path, description):
            all_passed = False

    if not check_has_scripts():
        all_passed = False

    # 2. Optional files
    print("\nOptional files (Week 4/6 bonus):")
    optional_count = 0
    for rel_path, description in OPTIONAL_FILES.items():
        if check_optional_file(rel_path, description):
            optional_count += 1
    if optional_count > 0:
        print(f"  {optional_count} optional file(s) present — eligible for bonus points")

    # 3. Gitingestignore contents
    print("\nGitingestignore check:")
    if not check_gitingestignore_entries():
        warnings = True

    # 4. Submission sections
    print("\nSubmission document sections:")
    passed, _ = check_sections(
        WEEK_DIR / "submission.md",
        SUBMISSION_REQUIRED_SECTIONS,
        "submission.md",
    )
    if not passed:
        all_passed = False

    # 5. Student names
    print("\nStudent names:")
    names_passed, names = check_student_names()
    if not names_passed:
        all_passed = False

    # 6. Product name
    print("\nProduct name:")
    if not check_product_name():
        warnings = True

    # 7. Loom link
    print("\nVideo link:")
    if not check_loom_link():
        all_passed = False

    # 8. Video transcript
    print("\nVideo transcript:")
    if not check_video_transcript():
        all_passed = False

    # 9. Template check
    print("\nTemplate check:")
    if not check_submission_not_template():
        warnings = True

    # 10. Submission .txt naming and size
    print("\nSubmission file:")
    name_ok, txt_path = check_submission_filename(names)
    if not name_ok:
        all_passed = False

    if txt_path and txt_path.exists():
        if not check_submission_size(txt_path):
            all_passed = False

        # 11. Content checks on the .txt
        print("\nSubmission content checks:")
        if not check_required_files_in_txt(txt_path):
            all_passed = False
        if not check_file_count(txt_path):
            all_passed = False
        if not check_no_data_bloat(txt_path):
            all_passed = False
        if not check_no_secrets(txt_path):
            all_passed = False
        if not check_no_binary(txt_path):
            warnings = True
        if not check_large_files(txt_path):
            warnings = True

    # Summary
    print("\n" + "=" * 60)
    if all_passed and not warnings:
        print("  All checks passed. Ready to submit.")
    elif all_passed and warnings:
        print("  Checks passed with warnings. Review warnings above.")
    else:
        print("  Some checks failed. Fix the issues above before submitting.")
    print("=" * 60)

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
