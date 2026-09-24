"""Browser parser tests use intercepted synthetic pages, NEVER a live site."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from browser_capture import FinalityGuard
from core import Store,analyze

ROOT=Path(__file__).resolve().parents[1]

class DOMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest("Playwright not installed; core tests require no third-party package")
        cls.pw=sync_playwright().start()
        executable=os.environ.get("RECORDER_TEST_CHROMIUM") or shutil.which("chromium")
        try:
            cls.browser=cls.pw.chromium.launch(headless=True,**({"executable_path":executable} if executable else {"channel":"chromium"}))
        except Exception as exc:
            cls.pw.stop()
            raise unittest.SkipTest("Install Chromium to run DOM tests: "+str(exc)[:150])
        cls.extractor=(ROOT/"web/extractor.js").read_text(encoding="utf-8")
    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.context=self.browser.new_context()
        self.page=self.context.new_page()
        self.page.route("**/*",lambda route:route.abort())
    def tearDown(self):
        self.context.close()
    def extract(self,html,selector='a[href*="/game/"]'):
        self.page.set_content('<base href="https://www.ethercrash.io/">'+html)
        return self.page.evaluate(self.extractor,{"selector":selector,"testMode":True})
    def test_extract_completed_ids_in_numeric_order(self):
        r=self.extract('<a href="/game/102">2.00x</a> <a href="/game/101">1.99x</a> <a href="/game/100">10.00x</a>')
        self.assertTrue(r["ok"])
        self.assertEqual([x["round_id"] for x in r["rows"]],[100,101,102])
        self.assertEqual([x["cents"] for x in r["rows"]],[1000,199,200])
    def test_non_history_live_and_player_data_ignored(self):
        r=self.extract('<h1 id="live">984.22x</h1><a href="/user/A">2.50x</a><a href="/game/99">Player cashout 2.00x $500</a><a href="/game/100">10.00x</a><a href="/game/101">1.50x</a>')
        self.assertEqual([x["round_id"] for x in r["rows"]],[100,101])
    def test_conflicting_duplicates_block_batch(self):
        r=self.extract('<a href="/game/100">1.00x</a><a href="/game/100">2.00x</a><a href="/game/101">1.00x</a>')
        self.assertFalse(r["ok"]);self.assertEqual(r["rows"],[])
    def test_identical_duplicates_deduped(self):
        r=self.extract('<a href="/game/100">2.00x</a><a href="/game/100">2.00x</a><a href="/game/101">1.00x</a>')
        self.assertEqual(len(r["rows"]),2)
    def test_invalid_selector_and_empty_dom(self):
        self.assertFalse(self.extract('<div>100.00x</div>', '[[[')["ok"])
        self.assertFalse(self.extract('<div>100.00x</div>')["ok"])
    def test_external_and_hidden_links_ignored(self):
        r=self.extract('<a href="https://evil.example/game/9">2.00x</a><a style="display:none" href="/game/99">1.00x</a><a href="/game/100">1.00x</a><a href="/game/101">2.00x</a>')
        self.assertEqual([x["round_id"] for x in r["rows"]],[100,101])
    def test_wrong_origin_rejected(self):
        self.page.set_content('<a href="/game/100">1.00x</a><a href="/game/101">2.00x</a>')
        r=self.page.evaluate(self.extractor,{"selector":'a[href*="/game/"]',"testMode":False})
        self.assertFalse(r["ok"])
    def test_calibrated_selector_ignores_neighboring_values(self):
        r=self.extract('<section id="history"><a href="/game/100">10.00x</a><a href="/game/101">1.00x</a></section><aside><a href="/game/100">2.00x</a></aside>', '#history a')
        self.assertTrue(r["ok"])
    def test_dom_guard_store_analysis_pipeline(self):
        vals=[10,1,1,1,1,1,2,10,1]
        html=' '.join(f'<a href="/game/{100+i}">{x:.2f}x</a>' for i,x in enumerate(vals))
        snapshot=self.extract(html)
        g=FinalityGuard()
        self.assertEqual(g.process(snapshot["rows"])[0],[])
        accepted,pending=g.process(snapshot["rows"])
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/"rounds.sqlite3")
            store.ingest("ethercrash",accepted,source="synthetic_dom")
            r=analyze(store.snapshot("ethercrash")[1])
            self.assertEqual(r["max_loss_streak"],2)
            self.assertEqual(r["complete_windows"],1)
            self.assertEqual(r["active_outcomes"]["wins"],2)
            self.assertEqual(pending["round_id"],108)
            store.close()

if __name__=="__main__":unittest.main()
