"""End-to-end tests: resume upload -> RUN -> pipeline -> jobs API.

External HTTP is mocked with respx (fixtures shaped like the real public APIs);
the application code paths are the real ones.
"""
import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.connectors.ats import AshbyConnector, GreenhouseConnector, LeverConnector
from app.connectors.base import SearchContext
from app.services.http import PoliteHttp

NOW = datetime.now(timezone.utc)
ISO = (NOW - timedelta(days=2)).isoformat()

GH_JOBS = {"jobs": [
    {"id": 101, "title": "Backend Engineer (Python)", "updated_at": ISO, "first_published": ISO,
     "company_name": "Tiny Startup", "location": {"name": "Bengaluru, India"},
     "absolute_url": "https://job-boards.greenhouse.io/tinystartup/jobs/101",
     "content": "&lt;p&gt;We are a team of 20 people. You will build REST APIs with Python, FastAPI, PostgreSQL on AWS. 1-3 years experience.&lt;/p&gt;"},
    {"id": 102, "title": "Account Executive", "updated_at": ISO, "company_name": "Tiny Startup",
     "location": {"name": "Mumbai"}, "absolute_url": "https://job-boards.greenhouse.io/tinystartup/jobs/102",
     "content": "Sales role"},
]}
LEVER_JOBS = [{
    "id": "abc-1", "text": "GenAI Engineer", "createdAt": int((NOW - timedelta(days=1)).timestamp() * 1000),
    "categories": {"location": "Remote - India", "commitment": "Full-time"}, "workplaceType": "remote",
    "hostedUrl": "https://jobs.lever.co/midco/abc-1", "applyUrl": "https://jobs.lever.co/midco/abc-1/apply",
    "description": "<p>Build RAG systems with LangChain, Python and pgvector. 2+ years experience.</p>",
    "lists": [{"text": "Requirements", "content": "<li>Python</li><li>LLM</li>"}],
    "salaryRange": {"min": 1500000, "max": 2500000, "currency": "INR", "interval": "per-year-salary"},
}]
REMOTEOK = [{"legal": "notice"}, {
    "id": "9001", "epoch": int(NOW.timestamp()) - 3600, "date": ISO, "company": "Tiny Startup",
    "position": "Backend Engineer (Python)", "tags": ["python", "fastapi"], "location": "Bengaluru, India",
    "description": "We are a team of 20 people. You will build REST APIs with Python, FastAPI, PostgreSQL on AWS. 1-3 years experience.",
    "apply_url": "https://job-boards.greenhouse.io/tinystartup/jobs/101?utm_source=remoteok",
    "url": "https://remoteok.com/remote-jobs/9001",
}, {
    "id": "9002", "epoch": int(NOW.timestamp()) - 7200, "date": ISO, "company": "Node Shop",
    "position": "Senior Node.js Developer", "tags": ["node", "javascript"], "location": "Remote",
    "description": "Node.js, Express.js, MongoDB, Docker. 5+ years experience.", "salary_min": 90000, "salary_max": 120000,
    "apply_url": "https://nodeshop.example/apply/9002", "url": "https://remoteok.com/remote-jobs/9002",
}]
REMOTIVE = {"jobs": [{
    "id": 77, "url": "https://remotive.com/remote-jobs/software-dev/77", "title": "Python Developer",
    "company_name": "Data Corp", "candidate_required_location": "Worldwide", "publication_date": ISO,
    "job_type": "full_time", "salary": "", "description": "<p>Python, Django, REST APIs. 2-4 years.</p>", "tags": []}]}


def mock_world(router: respx.MockRouter, *, gh=GH_JOBS):
    router.get("https://remoteok.com/api").mock(return_value=httpx.Response(200, json=REMOTEOK))
    router.get(url__regex=r"https://remotive\.com/api/remote-jobs.*").mock(
        side_effect=lambda req: httpx.Response(200, json=REMOTIVE if "software-dev" in str(req.url) else {"jobs": []}))
    router.get("https://boards-api.greenhouse.io/v1/boards/tinystartup/jobs").mock(return_value=httpx.Response(200, json=gh))
    router.get("https://api.lever.co/v0/postings/midco").mock(return_value=httpx.Response(200, json=LEVER_JOBS))
    # everything else (ATS probes, homepages, robots.txt) -> 404
    router.route().mock(return_value=httpx.Response(404))


# ---------------------------------------------------------------- connectors
@pytest.mark.asyncio
async def test_ats_connectors_parse():
    ctx = SearchContext(keywords=["Backend Developer"])
    with respx.mock(assert_all_called=False) as router:
        router.get("https://api.ashbyhq.com/posting-api/job-board/aico").mock(return_value=httpx.Response(200, json={"jobs": [
            {"id": "x1", "title": "AI Engineer", "location": "Pune", "isRemote": False, "workplaceType": "Hybrid",
             "descriptionHtml": "<p>LLM work</p>", "publishedAt": ISO, "employmentType": "FullTime",
             "jobUrl": "https://jobs.ashbyhq.com/aico/x1", "applyUrl": "https://jobs.ashbyhq.com/aico/x1/application",
             "compensation": {"summaryComponents": [{"compensationType": "Salary", "currencyCode": "INR",
                                                     "minValue": 1000000, "maxValue": 2000000, "interval": "1 YEAR"}]}}]}))
        mock_world(router)
        async with PoliteHttp() as http:
            gh = await GreenhouseConnector().fetch_company(http, "tinystartup", None, ctx)
            lv = await LeverConnector().fetch_company(http, "midco", "MidCo", ctx)
            ab = await AshbyConnector().fetch_company(http, "aico", "AICo", ctx)
            missing = await GreenhouseConnector().fetch_company(http, "doesnotexist", None, ctx)
    assert len(gh) == 2 and gh[0].company_name == "Tiny Startup" and gh[0].is_official
    assert lv[0].work_mode == "remote" and lv[0].salary_min == 1500000
    assert ab[0].work_mode == "hybrid" and ab[0].salary_currency == "INR"
    assert missing == []


@pytest.mark.asyncio
async def test_robots_txt_respected():
    from app.connectors.career_page import GenericCareerPageConnector
    from app.services.http import RobotsDisallowed
    with respx.mock(assert_all_called=False) as router:
        router.get("https://blocked.example/robots.txt").mock(return_value=httpx.Response(200, text="User-agent: *\nDisallow: /"))
        page = router.get("https://blocked.example/careers").mock(return_value=httpx.Response(200, text="<html></html>"))
        async with PoliteHttp() as http:
            with pytest.raises(RobotsDisallowed):
                await GenericCareerPageConnector().fetch_company(http, "https://blocked.example/careers", "B", SearchContext(keywords=[]))
        assert not page.called


# ---------------------------------------------------------------- end-to-end
@pytest.fixture
async def client(monkeypatch):
    from app import db as dbmod
    from app.main import app
    from app.services import company_discovery
    # bootstrap boards replaced by two test companies (a small one and a mid-size one)
    monkeypatch.setattr(company_discovery, "SEED_BOARDS", {"greenhouse": ["tinystartup"], "lever": ["midco"]})
    async with dbmod.engine.begin() as conn:
        await conn.run_sync(dbmod.Base.metadata.drop_all)
        await conn.run_sync(dbmod.Base.metadata.create_all)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def _auth(client) -> dict:
    r = await client.post("/api/auth/register", json={"email": "priya@example.com", "password": "s3cret-pass!", "full_name": "Priya"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _wait(client, h, sid, timeout=60):
    for _ in range(timeout * 10):
        r = await client.get(f"/api/search/status/{sid}", headers=h)
        if r.json()["status"] in ("completed", "failed", "cancelled"):
            return r.json()
        await asyncio.sleep(0.1)
    raise AssertionError("search did not finish")


@pytest.mark.asyncio
async def test_full_workflow(client, resume_docx):
    h = await _auth(client)
    assert (await client.get("/api/jobs", headers={})).status_code == 401
    assert (await client.post("/api/search/run", headers=h)).status_code == 400  # no resume yet

    # bad upload rejected
    r = await client.post("/api/resume/upload", headers=h, files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 422

    r = await client.post("/api/resume/upload", headers=h, files={"file": ("priya.docx", resume_docx, "application/octet-stream")})
    assert r.status_code == 201, r.text
    prof = r.json()
    assert prof["candidate"] == "Priya Sharma" and "LangChain" in prof["skills"]
    assert prof["internship_experience_months"] == 7

    # user edits profile & preferences
    r = await client.put("/api/resume/profile", headers=h, json={"skills": prof["skills"] + ["pgvector", "LLM"],
                                                                  "job_roles": ["Backend Developer", "GenAI Engineer"]})
    assert r.status_code == 200 and "pgvector" in r.json()["skills"]
    prefs = (await client.get("/api/resume/preferences", headers=h)).json()
    prefs.pop("suggested")
    prefs.update({"preferred_locations": ["Bengaluru"], "countries": ["india"], "min_match_score": 30})
    assert (await client.put("/api/resume/preferences", headers=h, json=prefs)).status_code == 200

    with respx.mock(assert_all_called=False) as router:
        mock_world(router)
        r = await client.post("/api/search/run", headers=h)
        assert r.status_code == 202, r.text
        sid = r.json()["search_id"]
        # a second click while running is rejected (or the first already finished)
        r2 = await client.post("/api/search/run", headers=h)
        assert r2.status_code in (409, 202)
        if r2.status_code == 202:
            await _wait(client, h, r2.json()["search_id"])
        done = await _wait(client, h, sid)

    assert done["status"] == "completed", done
    st = done["stats"]
    assert done["source_results"]["remoteok"]["status"] == "ok"
    assert done["source_results"]["jsearch"]["status"] == "needs_credentials"
    assert st["companies_checked"] >= 2
    assert any("Keywords" in l["message"] for l in done["logs"])

    jobs = (await client.get("/api/jobs", headers=h, params={"page_size": 50})).json()
    titles = [j["title"] for j in jobs["items"]]
    # Account Executive (non-tech) filtered; Greenhouse + RemoteOK copies merged into ONE card
    assert "Account Executive" not in titles
    assert titles.count("Backend Engineer (Python)") == 1
    be = next(j for j in jobs["items"] if j["title"] == "Backend Engineer (Python)")
    assert {s["key"] for s in be["sources"]} == {"greenhouse", "remoteok"}
    assert be["is_official"] and be["sources"][0]["is_official"]
    assert be["company"]["size_category"] == "small" and be["company"]["employee_count"] == 20
    assert be["match"]["is_new"] and be["match"]["score"] >= 70
    assert "Python" in be["match"]["matched_skills"]
    node = next(j for j in jobs["items"] if "Node.js" in j["title"])
    assert node["company"]["size_label"] == "Size not verified"
    assert node["salary"] != "Not specified"
    remotive = next(j for j in jobs["items"] if j["title"] == "Python Developer")
    assert remotive["salary"] == "Not specified"  # never fabricated

    # filters & sorting
    small = (await client.get("/api/jobs", headers=h, params={"company_size": "small"})).json()
    assert all(j["company"]["size_category"] == "small" for j in small["items"]) and small["total"] >= 1
    remote = (await client.get("/api/jobs", headers=h, params={"work_mode": "remote"})).json()
    assert all(j["work_mode"] == "remote" for j in remote["items"])
    sk = (await client.get("/api/jobs", headers=h, params={"skills": "LangChain"})).json()
    assert sk["total"] >= 1 and all("LangChain" in j["skills"] for j in sk["items"])

    # detail, save, hide
    d = (await client.get(f"/api/jobs/{be['id']}", headers=h)).json()
    assert "breakdown" in d["match"] and d["description"]
    assert (await client.post(f"/api/jobs/{be['id']}/save", headers=h)).status_code == 201
    assert len((await client.get("/api/jobs/saved", headers=h)).json()) == 1
    assert (await client.post(f"/api/jobs/{node['id']}/hide", headers=h)).status_code == 200
    ids = [j["id"] for j in (await client.get("/api/jobs", headers=h, params={"page_size": 50})).json()["items"]]
    assert node["id"] not in ids

    stats = (await client.get("/api/dashboard/stats", headers=h)).json()
    assert stats["total_jobs"] >= 3 and stats["small_company_jobs"] >= 1

    # ---- second RUN: Greenhouse job 101 removed from the official board -> unavailable; no duplicates
    gh2 = {"jobs": [GH_JOBS["jobs"][1], {
        "id": 103, "title": "AI Engineer", "updated_at": ISO, "company_name": "Tiny Startup",
        "location": {"name": "Bengaluru"}, "absolute_url": "https://job-boards.greenhouse.io/tinystartup/jobs/103",
        "content": "LLM, RAG, LangChain, Python. 1+ years experience."}]}
    with respx.mock(assert_all_called=False) as router:
        mock_world(router, gh=gh2)
        sid2 = (await client.post("/api/search/run", headers=h)).json()["search_id"]
        done2 = await _wait(client, h, sid2)
    assert done2["status"] == "completed"
    all_jobs = (await client.get("/api/jobs", headers=h, params={"page_size": 100, "include_unavailable": True,
                                                                  "include_hidden": True})).json()["items"]
    keys = [(j["title"], j["company"]["name"]) for j in all_jobs]
    assert len(keys) == len(set(keys)), "duplicate job records created"
    new = [j for j in all_jobs if j["match"]["is_new"]]
    assert [j["title"] for j in new] == ["AI Engineer"]
    be2 = next(j for j in all_jobs if j["id"] == be["id"])
    # still listed by RemoteOK, so job stays active but the Greenhouse link is marked unavailable
    gh_link = next(s for s in be2["sources"] if s["key"] == "greenhouse")
    assert gh_link["status"] == "unavailable"

    hist = (await client.get("/api/search/history", headers=h)).json()
    assert hist["total"] >= 2
    comps = (await client.get("/api/companies", headers=h, params={"size": "small"})).json()
    assert any(c["name"] == "Tiny Startup" for c in comps["items"])
    srcs = (await client.get("/api/sources", headers=h)).json()
    assert any(s["key"] == "linkedin" and s["status"] == "via_provider" for s in srcs)


@pytest.mark.asyncio
async def test_failed_source_does_not_stop_search_and_stop_works(client, resume_docx):
    h = await _auth(client)
    await client.post("/api/resume/upload", headers=h, files={"file": ("cv.docx", resume_docx, "application/octet-stream")})
    with respx.mock(assert_all_called=False) as router:
        router.get("https://remoteok.com/api").mock(return_value=httpx.Response(500))
        router.get(url__regex=r"https://remotive\.com/.*").mock(side_effect=httpx.ConnectError("boom"))
        router.get("https://boards-api.greenhouse.io/v1/boards/tinystartup/jobs").mock(return_value=httpx.Response(200, json=GH_JOBS))
        router.route().mock(return_value=httpx.Response(404))
        sid = (await client.post("/api/search/run", headers=h)).json()["search_id"]
        done = await _wait(client, h, sid)
    assert done["status"] == "completed"
    assert done["source_results"]["remoteok"]["status"] == "error"
    assert done["source_results"]["remotive"]["status"] == "error"
    assert done["stats"]["official_postings"] >= 1  # career pages still collected

    # stop: request cancellation on a slow run
    async def slow(req):
        await asyncio.sleep(1.5)
        return httpx.Response(200, json=REMOTEOK)
    with respx.mock(assert_all_called=False) as router:
        router.get("https://remoteok.com/api").mock(side_effect=slow)
        router.route().mock(return_value=httpx.Response(404))
        sid = (await client.post("/api/search/run", headers=h)).json()["search_id"]
        await asyncio.sleep(0.3)
        assert (await client.post(f"/api/search/stop/{sid}", headers=h)).status_code == 200
        done = await _wait(client, h, sid)
    assert done["status"] == "cancelled"
