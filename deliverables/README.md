# Deliverables

Built documents, committed so they travel with the release. Each is generated
from sources in this repository; rebuild rather than edit them.

| File | What it is | Rebuilt by |
|---|---|---|
| `Consilium-Leadership-Briefing.pptx` | Leadership briefing: the product, what was built, evidence, roadmap (49 slides) | the deck sources, from `docs/delivery/` facts |
| `Consilium-Onboarding-Guide.pdf` / `.docx` | Business onboarding guide: every menu, page and button, with annotated screenshots (217 pages) | `scripts/capture_screenshots.py`, then `scripts/build_guides.sh`, from `docs/guides/` |
| `Consilium-Requirements-Coverage.xlsx` | Requirement → where it lives → test, with epics and stories | `scripts/coverage_to_xlsx.py`, from `docs/delivery/REQUIREMENTS-COVERAGE.md` and `EPICS.md` |

Demonstration logins are described in
[`docs/delivery/DEMO-LOGINS.md`](../docs/delivery/DEMO-LOGINS.md). The sandbox
password itself is never written into these documents.
