"""End-to-end pipeline test with a fake resolver/fetcher/verifier and the
mock Zotero server. Proves: extraction → verification → review gate →
dedup (URL match to seeded item) → collection structure → batched write
with a survived 412 → mapping file + report. Run: python dev/test_end_to_end.py"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from citetool.pipeline import Pipeline
from citetool.zotero_client import ZoteroClient
from citetool.claude_verify import VerifiedItem, build_prompt, parse_response
from citetool.fetch import PageContent
from dev import mock_zotero

DOC = Path(__file__).parent / "test_document.docx"


def fake_resolver(url):
    if "doi.org" in url:
        return ({"itemType": "journalArticle", "title": "A translated article",
                 "DOI": "10.1000/example123",
                 "creators": [{"creatorType": "author", "firstName": "Jane",
                               "lastName": "Smith"}]}, "CrossRef (DOI)")
    return (None, "no translator match")


def fake_fetcher(url):
    if "health.gov.au" in url:
        return PageContent(url=url, final_url=url, ok=True, status=200,
                           title="Home | Department of Health",
                           text="National Preventive Health Strategy. Published 13 December 2021. © Commonwealth of Australia")
    if "unreachable" in url:
        return PageContent(url=url, ok=False, error="could not connect")
    return PageContent(url=url, final_url=url, ok=True, status=200,
                       title="Some page", text="Some text about the thing.")


class FakeVerifier:
    """Scripted Claude: one clean, one flagged gov report, one journal
    article from translator data, one honest unresolvable."""

    def verify(self, url, anchor, raw, page):
        if "health.gov.au" in url:
            return VerifiedItem(True, item={
                "itemType": "report", "title": "National Preventive Health Strategy 2021–2030",
                "creators": [{"creatorType": "author", "name": "Australian Government Department of Health"}],
                "date": "2021-12-13", "institution": "Department of Health", "url": url,
                "bogusField": "should be dropped by schema validation",
            }, flags=[{"field": "date", "note": "taken from body text, not metadata"}])
        if raw:  # translator worked — Claude confirms
            item = dict(raw); item["url"] = url
            return VerifiedItem(True, item=item, flags=[])
        if "unreachable" in url or "abs.gov.au" in url:
            return VerifiedItem(False, reason="page unreachable and translators returned nothing")
        return VerifiedItem(True, item={
            "itemType": "webpage", "title": f"Page for {anchor}",
            "creators": [{"creatorType": "author", "name": "Anthropic"}],
            "url": url, "websiteTitle": "Anthropic"}, flags=[])


def main():
    assert DOC.exists(), "run dev/make_test_doc.py first"
    server, state, base = mock_zotero.start()
    try:
        z = ZoteroClient("test-key", base_url=base)
        summary_info = z.connection_summary()
        assert summary_info["write"] and summary_info["user_id"] == "1"

        schema = json.loads((Path(__file__).parents[1] / "citetool" / "data" /
                             "schema-fallback.json").read_text())
        events = []
        pipe = Pipeline(resolver=fake_resolver, fetcher=fake_fetcher,
                        verifier=FakeVerifier(), zotero=z, schema=schema,
                        progress=lambda u, s, d: events.append((u, s, d)))

        extraction = pipe.load_document(str(DOC))
        assert len(extraction.links) == 6, f"expected 6 links, got {len(extraction.links)}"
        assert len(pipe.proposals) == 5, "L001+L005 share a URL -> 5 unique"

        pipe.run_metadata()
        by_url = {p.url: p for p in pipe.proposals}
        gov = by_url["https://www.health.gov.au/resources/publications/example-report"]
        assert gov.status == "flagged" and gov.item["title"].startswith("National Preventive")
        assert "bogusField" not in gov.item and any("bogusField" in pr for pr in gov.schema_problems)
        assert gov.item["creators"][0]["name"].startswith("Australian Government")
        assert by_url["https://www.abs.gov.au/statistics/example"].status == "unresolvable"
        assert by_url["https://doi.org/10.1000/example123"].status == "ready"

        # review gate: everything ready/flagged is pre-approved; nothing written yet
        assert not any(k.startswith("ITEM") for k in state.items)

        summary = pipe.commit()
        c = summary["counts"]
        assert c["matched-existing"] == 1, c   # anthropic.com/claude matched seed by URL
        assert c["added"] == 3, c              # gov report + journal article + AIHW page
        assert c["failed"] == 1, c             # the unresolvable one
        assert state.forced_412s == 0, "the deliberate 412 was consumed (retry worked)"

        # collections: parent 'Cited Documents' -> sub 'test_document', items inside
        colls = {v["name"]: v for v in state.collections.values()}
        assert "Cited Documents" in colls and "test_document" in colls
        sub = colls["test_document"]["key"]
        assert colls["test_document"]["parentCollection"] == colls["Cited Documents"]["key"]
        created = [v for k, v in state.items.items() if k.startswith("ITEM")]
        assert all(sub in v.get("collections", []) for v in created), \
            "new items must be assigned to the subcollection at creation time"
        assert sub in state.items["EXIST001"]["collections"], \
            "matched existing item must be added to the collection via PATCH"

        # v2 mapping file
        citemap = json.loads(DOC.with_suffix(".citemap.json").read_text())
        assert citemap["zotero"]["library_id"] == "1"
        by_id = {l["link_id"]: l for l in citemap["links"]}
        assert by_id["L001"]["item_key"] == "EXIST001"
        assert by_id["L005"]["item_key"] == "EXIST001", "same URL -> same item key"
        assert by_id["L003"]["status"] == "failed" and by_id["L003"]["failure_reason"]
        assert by_id["L002"]["item_key"].startswith("ITEM")

        # prompt/parse round-trip for the real verifier's contract
        v = parse_response('```json\n{"resolvable": true, "item": {"itemType":"report",'
                           '"title":"T"}, "flags": [{"field":"date","note":"n"}]}\n```', "sonnet")
        assert v.resolvable and v.flags[0]["field"] == "date"
        p = build_prompt("https://x", "anchor", None, fake_fetcher("https://x"))
        assert "Respond with ONLY this JSON" in p and "single-field creator" in p

        print("ALL END-TO-END CHECKS PASSED")
        print(f"  events emitted: {len(events)}; counts: {c}")
        print(f"  collections: {[v['name'] for v in state.collections.values()]}")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
