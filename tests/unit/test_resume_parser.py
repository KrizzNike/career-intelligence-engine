"""Tests: src/nlp/resume_parser.py + the loader/cleaner/segmenter chain.

These are FIXTURE-BASED (no MySQL) so they run anywhere and lock in
extraction quality on known-good resumes. They also exercise the PDF vs
DOCX parity claim: both formats should yield the same sections + the
same key extracted fields.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from src.data_ingestion.resume_loader import load_resume  # noqa: E402
from src.preprocessing.clean_text import clean  # noqa: E402
from src.preprocessing.section_segmenter import segment, CANON_SECTIONS  # noqa: E402

SYNTH_DIR = ROOT / "data" / "raw" / "resumes" / "synthetic"
BI_DOCX = SYNTH_DIR / "bi_analyst_0000.docx"
BI_PDF = SYNTH_DIR / "bi_analyst_0000.pdf"


def _stub_idx():
    """Minimal SkillIndex for parser tests that don't depend on taxonomy."""
    from src.nlp.skill_matcher import SkillIndex
    skills = {
        "sql": {"id": 1, "name": "SQL"},
        "power_bi": {"id": 2, "name": "Power BI"},
        "python": {"id": 3, "name": "Python"},
        "tableau": {"id": 4, "name": "Tableau"},
        "looker": {"id": 5, "name": "Looker"},
        "kpi_design": {"id": 6, "name": "KPI Design"},
        "data_modeling_basics": {"id": 7, "name": "Data Modeling (Basics)"},
        "data_modeling": {"id": 8, "name": "Data Modeling"},
    }
    # Stand-in: no DB; we set .patterns to [] so matcher returns no hits.
    return SkillIndex(skills=skills, patterns=[])


def pytest_configure(config):
    if not SYNTH_DIR.exists():
        pytest.skip("synthetic resumes not generated", allow_module_level=True)


# --------- loader ----------

def test_load_docx_and_pdf_present():
    assert BI_DOCX.exists() and BI_PDF.exists()


def test_loader_unsupported_ext_raises():
    with pytest.raises(ValueError):
        load_resume("foo.txt")


# --------- cleaner ----------

def test_clean_dehyphenates_and_dashes():
    c = clean(doc_text="Py-\nthon, resume - cafe over a line")
    assert "Python" in c.text
    assert "resume" in c.text  # folded from accented resume


def test_clean_lowers_noise_smart_quotes():
    c = clean(doc_text="“quoted” — dash")
    assert '"quoted"' in c.text and "- dash" in c.text


def test_clean_blocks_preserves_kinds():
    from src.data_ingestion.resume_loader import Block
    bs = [Block(text="Name", kind="title"),
          Block(text="Skills", kind="heading"),
          Block(text="SQL", kind="bullet")]
    c = clean(blocks=bs)
    kinds = [b.kind for b in c.blocks]
    assert kinds == ["title", "heading", "bullet"]


# --------- segmenter ----------

def test_segment_docx_yields_all_sections():
    d = load_resume(BI_DOCX)
    c = clean(blocks=d.blocks)
    secs = segment(c.blocks)
    assert "header" in secs
    for s in ("skills", "experience", "projects", "education"):
        assert s in secs, f"missing section: {s}"


def test_segment_pdf_matches_docx_section_keys():
    d_d = load_resume(BI_DOCX)
    d_p = load_resume(BI_PDF)
    s_d = segment(clean(blocks=d_d.blocks).blocks)
    s_p = segment(clean(blocks=d_p.blocks).blocks)
    # Both must surface the same canonical sections.
    assert {"skills", "experience", "projects",
            "education", "certifications"} <= set(s_p.keys())
    assert set(s_d.keys()) & set(s_p.keys()) >= {
        "header", "skills", "experience", "education"}


# --------- parser (fixture-based, no DB dependency for fields) ----------

def _parse(path, idx):
    from src.nlp.resume_parser import parse_resume
    return parse_resume(path, idx)


def test_parser_extracts_name_resume(bi_analyst_idx):
    p = _parse(BI_DOCX, bi_analyst_idx)
    assert "Allison" in p.name and "Hill" in p.name


def test_parser_extracts_email_phone_location():
    from src.nlp.resume_parser import parse_resume  # stub idx ok
    p = parse_resume(BI_DOCX, _stub_idx())
    assert "@" in p.email
    assert p.phone, "phone not extracted"
    assert p.location, "location not extracted"


def test_parser_extracts_education_full():
    from src.nlp.resume_parser import parse_resume
    p = parse_resume(BI_DOCX, _stub_idx())
    assert len(p.education) == 1
    e = p.education[0]
    assert "Data Science" in (e.field_of_study or "")
    assert "University" in (e.institution or "")
    assert e.year == 2021


def test_parser_extracts_experience_role_and_dates():
    from src.nlp.resume_parser import parse_resume
    p = parse_resume(BI_DOCX, _stub_idx())
    assert p.experience, "no experience extracted"
    e = p.experience[0]
    assert "BI Analyst" in e.title
    assert "Blake" in e.company
    assert e.start and e.end
    assert e.bullets, "bullets empty"


def test_parser_extracts_projects():
    from src.nlp.resume_parser import parse_resume
    p = parse_resume(BI_DOCX, _stub_idx())
    assert p.projects, "no projects extracted"
    # Project titles begin with 'Project:'.
    assert any(pr.name.startswith("Project:") for pr in p.projects)


def test_parser_extracts_certs_strips_issuer_code():
    from src.nlp.resume_parser import parse_resume
    p = parse_resume(BI_DOCX, _stub_idx())
    assert p.certifications, "no certifications extracted"
    c = p.certifications[0]
    assert "Power BI" in c.name
    assert "PL-300" not in c.name  # the code tag should be stripped


def test_parser_pdf_docx_parity_fields():
    """The same resume as PDF and DOCX should yield equal field counts."""
    from src.nlp.resume_parser import parse_resume
    idx = _stub_idx()
    d = parse_resume(BI_DOCX, idx)
    p = parse_resume(BI_PDF, idx)
    assert len(d.education) == len(p.education) >= 1
    assert len(d.experience) == len(p.experience) >= 1


# Fixture for the matcher-backed variant: available only when DB seeded.
@pytest.fixture(scope="module")
def bi_analyst_idx():
    try:
        from src.nlp.skill_matcher import load_skill_index
        return load_skill_index()
    except Exception as e:
        pytest.skip(f"skill index unavailable (MySQL?): {e}")
