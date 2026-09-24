import csv
import io
import json
import random
import tempfile
import unittest
from pathlib import Path

from core import Store, analyze, parse_crash, parse_id, read_csv_text, export_to_vault, export_root, wilson
from browser_capture import FinalityGuard, BrowserCapture, validate_url


def rows(values,start=100):
    return [{"round_id":start+i,"cents":parse_crash(v)} for i,v in enumerate(values)]


class RuleTests(unittest.TestCase):
    def test_no_anchor_no_qualification(self):
        r=analyze(rows([1,1,1,1,1,2,3,1]))
        self.assertEqual(r["window_count"],0)

    def test_exact_anchor_trigger_and_next_round(self):
        r=analyze(rows([10,1,1,1,2]))
        self.assertEqual(r["first_entries"]["n"],1)
        self.assertEqual(r["active_outcomes"]["n"],1)
        self.assertEqual(r["active_outcomes"]["wins"],1)
        self.assertEqual(r["windows"][0]["trigger_id"],103)
        self.assertEqual(r["windows"][0]["first_active_id"],104)
        self.assertEqual(r["max_loss_streak"],0)

    def test_no_lookahead_on_third_red(self):
        r=analyze(rows([10,1,1,1]))
        self.assertEqual(r["window_count"],1)
        self.assertEqual(r["first_entries"]["n"],0)
        self.assertEqual(r["state"]["label"],"QUALIFIED_FOR_NEXT_OBSERVED_ROUND")

    def test_qualifying_reds_are_consecutive(self):
        r=analyze(rows([10,1,1,2,1,1,1,2]))
        self.assertEqual(r["windows"][0]["trigger_id"],106)
        self.assertEqual(r["active_outcomes"]["n"],1)

    def test_reset_reanchors_while_waiting(self):
        r=analyze(rows([10,1,1,10,1,1,1,2]))
        self.assertEqual(r["windows"][0]["anchor_id"],103)
        self.assertEqual(r["windows"][0]["trigger_id"],106)

    def test_terminal_reset_is_active_win(self):
        r=analyze(rows([10,1,1,1,1.5,10]))
        self.assertEqual(r["active_outcomes"]["wins"],1)
        self.assertEqual(r["active_outcomes"]["losses"],1)
        self.assertEqual(r["complete_windows"],1)
        self.assertEqual(r["windows"][0]["reset_id"],105)
        self.assertEqual(r["state"]["anchor_id"],105)

    def test_ordinary_win_keeps_window_active(self):
        r=analyze(rows([10,1,1,1,2,2,1,2,10]))
        self.assertEqual(r["window_count"],1)
        self.assertEqual(r["active_outcomes"]["n"],5)
        self.assertEqual(r["max_win_streak"],2)

    def test_loss_max_excludes_three_qualifying_reds(self):
        r=analyze(rows([10]+[1]*10+[10]))
        self.assertEqual(r["max_loss_streak"],7)
        self.assertEqual(r["active_outcomes"]["losses"],7)
        self.assertEqual(r["loss_thresholds"][6]["complete_windows_reached"],1)

    def test_win_runs_not_joined_across_resets(self):
        r=analyze(rows([10,1,1,1,2,10,1,1,1,2,10]))
        self.assertEqual(r["max_win_streak"],2)
        self.assertEqual(r["complete_windows"],2)

    def test_gap_discards_eligibility(self):
        data=rows([10,1,1,1,1])+rows([1,1,2,10,1,1,1,2],106)
        r=analyze(data)
        self.assertEqual(r["gap_count"],1)
        self.assertEqual(r["missing_id_count"],1)
        self.assertEqual(r["windows"][0]["status"],"censored_gap")
        self.assertEqual(r["active_outcomes"]["losses"],1)
        self.assertEqual(r["active_outcomes"]["wins"],1)
        self.assertTrue(r["runs"][0]["right_censored"])

    def test_gap_during_qualification_requires_new_anchor(self):
        r=analyze(rows([10,1,1])+rows([1,2,1,1,1,2],104))
        self.assertEqual(r["window_count"],0)

    def test_conflict_discards_eligibility(self):
        data=rows([10,1,1,1,1,2,1,1,1,2])
        data[5]["conflicted"]=1
        r=analyze(data)
        self.assertEqual(r["conflicted_rounds"],1)
        self.assertEqual(r["windows"][0]["status"],"censored_conflict")
        self.assertEqual(r["active_outcomes"]["n"],1)

    def test_right_censored_open_run(self):
        r=analyze(rows([10,1,1,1,1,1]))
        self.assertEqual(r["max_loss_streak"],2)
        self.assertTrue(r["runs"][0]["right_censored"])
        self.assertEqual(r["runs"][0]["end_reason"],"data_end")
        self.assertEqual(r["incomplete_windows"],1)

    def test_first_entry_separate_from_continuation(self):
        r=analyze(rows([10,1,1,1,1,1,2,2,10]))
        self.assertEqual(r["first_entries"]["wins"],0)
        self.assertEqual(r["first_entries"]["n"],1)
        stats={x["preceding_active_losses"]:x for x in r["conditional_after_losses"]}
        self.assertEqual(stats[1]["wins"],0)
        self.assertEqual(stats[2]["wins"],1)

    def test_boundary_values(self):
        r=analyze(rows([9.99,1,1,1,10,1.99,1.99,1.99,2,10]))
        self.assertEqual(r["windows"][0]["anchor_id"],104)
        self.assertEqual(r["active_outcomes"]["wins"],2)
        self.assertEqual(r["active_outcomes"]["losses"],0)

    def test_zero_crash_is_loss(self):
        r=analyze(rows([10,0,0,0,0]))
        self.assertEqual(r["active_outcomes"]["losses"],1)

    def test_unordered_rejected(self):
        with self.assertRaises(ValueError): analyze(list(reversed(rows([10,1]))))
        with self.assertRaises(ValueError): analyze(rows([10])+rows([1]))

    def test_randomized_against_independent_mask_reference(self):
        rng=random.Random(62714)
        for _ in range(300):
            values=[rng.choice([100,150,199,200,250,999,1000,2100]) for i in range(80)]
            data=[{"round_id":i+1,"cents":c} for i,c in enumerate(values)]
            actual=analyze(data)
            expected=[]
            for i in range(len(values)):
                # Eligibility uses ONLY previous observations, and the most recent anchor.
                anchors=[j for j in range(i) if values[j]>=1000]
                if not anchors: continue
                a=anchors[-1]
                triggers=[j for j in range(a+3,i) if all(v<200 for v in values[j-2:j+1])]
                if triggers: expected.append(values[i]>=200)
            self.assertEqual(actual["active_outcomes"]["n"],len(expected))
            self.assertEqual(actual["active_outcomes"]["wins"],sum(expected))


class ParsingTests(unittest.TestCase):
    def test_exact_decimal(self):
        self.assertEqual(parse_crash("1.99x"),199)
        self.assertEqual(parse_crash("10.00"),1000)
        self.assertEqual(parse_crash("0.00"),0)

    def test_bad_values(self):
        for v in ["nan","inf","-1","2.001","1e3","1,25","1.00 2.00",True,None]:
            with self.assertRaises(ValueError,msg=str(v)): parse_crash(v)
        for v in [0,-1,"1.1","nan",True,"1234567890123456"]:
            with self.assertRaises(ValueError,msg=str(v)): parse_id(v)

    def test_csv_sort_dedupe(self):
        data=read_csv_text("round_id,crash\n3,2\n1,10\n2,1\n2,1\n","ethercrash")
        self.assertEqual([r["round_id"] for r in data],[1,2,3])

    def test_csv_reject_conflict_and_wrong_site(self):
        with self.assertRaises(ValueError): read_csv_text("round_id,crash\n1,2\n1,3\n","ethercrash")
        with self.assertRaises(ValueError): read_csv_text("site,round_id,crash\nother,1,2\n","ethercrash")
        with self.assertRaises(ValueError): read_csv_text("a,b\n1,2\n","ethercrash")

    def test_url_allowlist(self):
        self.assertEqual(validate_url("https://www.ethercrash.io/"),"https://www.ethercrash.io/")
        for url in ["http://ethercrash.io/","https://ethercrash.io.evil.example/","https://user:pass@ethercrash.io/","https://www.ethercrash.io/?token=secret"]:
            with self.assertRaises(ValueError): validate_url(url)

    def test_wilson_no_fake_precision_when_empty(self):
        self.assertIsNone(wilson(0,0)["rate"])
        self.assertAlmostEqual(wilson(50,100)["rate"],0.5)
        self.assertLess(wilson(50,100)["low"],0.5)
        self.assertGreater(wilson(50,100)["high"],0.5)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)
        self.store=Store(self.path/"rounds.sqlite3")
    def tearDown(self):
        self.store.close(); self.tmp.cleanup()
    def test_idempotence_and_reopen(self):
        a=self.store.ingest("ethercrash",rows([10,1,1,1,2]),source="test")
        b=self.store.ingest("ethercrash",rows([10,1,1,1,2]),source="test")
        self.assertEqual(a["inserted"],5);self.assertEqual(b["duplicates"],5)
        self.assertEqual(self.store.revision(),1)
        self.store.close();self.store=Store(self.path/"rounds.sqlite3")
        self.assertEqual(len(self.store.snapshot("ethercrash")[1]),5)
    def test_conflicting_fact_quarantined(self):
        self.store.ingest("ethercrash",rows([10,1,1,1,2]),source="test")
        result=self.store.ingest("ethercrash",rows([3],104),source="test")
        data=self.store.snapshot("ethercrash")[1]
        self.assertEqual(result["conflicts"],1)
        self.assertEqual(data[-1]["cents"],200)
        self.assertEqual(data[-1]["conflicted"],1)
        self.assertEqual(analyze(data)["usable_rounds"],4)
    def test_backfill_rebuilds_gap(self):
        data=rows([10,1,1,1,1,2,10]); incomplete=data[:4]+data[5:]
        self.store.ingest("ethercrash",incomplete,source="test")
        self.assertEqual(analyze(self.store.snapshot("ethercrash")[1])["gap_count"],1)
        self.store.ingest("ethercrash",[data[4]],source="backfill")
        r=analyze(self.store.snapshot("ethercrash")[1])
        self.assertEqual(r["gap_count"],0);self.assertEqual(r["complete_windows"],1)
        self.assertEqual(r["active_outcomes"]["losses"],1)
    def test_invalid_batch_atomic(self):
        with self.assertRaises(ValueError):self.store.ingest("ethercrash",[{"round_id":1,"cents":100},{"round_id":2,"cents":-1}],source="test")
        self.assertEqual(len(self.store.snapshot("ethercrash")[1]),0)
    def test_pending_not_final(self):
        self.store.set_pending("ethercrash",{"round_id":100,"cents":199})
        self.assertEqual(len(self.store.snapshot("ethercrash")[1]),0)
        self.assertEqual(len(self.store.diagnostics("ethercrash")["pending"]),1)
    def test_distinct_sites(self):
        self.store.ingest("ethercrash",rows([1]),source="test")
        self.store.ingest("other",rows([2]),source="test")
        self.assertEqual(self.store.snapshot("ethercrash")[1][0]["cents"],100)
    def test_vault_export_no_plugin_required(self):
        self.store.ingest("ethercrash",rows([10,1,1,1,1,2,10]),source="test")
        _,data=self.store.snapshot("ethercrash")
        report=analyze(data)
        vault=self.path/"vault";vault.mkdir()
        unrelated=vault/"Private note.md";unrelated.write_text("Do not change")
        dest=export_to_vault(vault,data,report,self.store.diagnostics("ethercrash"))
        self.assertEqual(unrelated.read_text(encoding="utf-8"),"Do not change")
        self.assertTrue((dest/"ethercrash Dashboard.md").exists())
        files=list((dest/"data").glob("*.csv"));self.assertEqual(len(files),1)
        parsed=list(csv.DictReader(io.StringIO(files[0].read_text(encoding="utf-8"))))
        self.assertEqual(len(parsed),7);self.assertEqual(parsed[0]["crash"],"10.00")
        export_to_vault(vault,data,report,self.store.diagnostics("ethercrash"))
    def test_refuses_unowned_export_folder(self):
        vault=self.path/"vault";vault.mkdir();(vault/"Crash Round Research").mkdir()
        with self.assertRaises(ValueError): export_root(vault)
    def test_refuses_missing_vault(self):
        with self.assertRaises(ValueError):export_root(self.path/"missing")
    def test_refuses_export_symlink(self):
        vault=self.path/"vault";vault.mkdir();other=self.path/"other";other.mkdir()
        try:(vault/"Crash Round Research").symlink_to(other,target_is_directory=True)
        except OSError:self.skipTest("Symlinks unavailable")
        with self.assertRaises(ValueError):export_root(vault)
    def test_capture_requires_review(self):
        cap=BrowserCapture(self.store,self.path)
        with self.assertRaises(ValueError):cap.calibrate(0,True)
        cap.status.update(running=True,preview=[{"round_id":1},{"round_id":2}])
        with self.assertRaises(ValueError):cap.calibrate(0,False)
        cap.calibrate(0,True);self.assertTrue(cap.approved)
        cap.set_selector("table a");self.assertFalse(cap.approved)


class FinalityTests(unittest.TestCase):
    def test_first_snapshot_cannot_finalize(self):
        g=FinalityGuard();ready,pending=g.process(rows([10,1,2]))
        self.assertEqual(ready,[]);self.assertEqual(pending["round_id"],102)
    def test_stability_and_newer_id_required(self):
        g=FinalityGuard();data=rows([10,1,2]);g.process(data)
        ready,pending=g.process(data)
        self.assertEqual([r["round_id"] for r in ready],[100,101])
        ready,pending=g.process(rows([10,1,2,3]))
        self.assertEqual([r["round_id"] for r in ready],[100,101,102])
    def test_changed_multiplier_waits(self):
        g=FinalityGuard();g.process(rows([10,1,2]))
        ready,_=g.process(rows([10,1.5,2]))
        self.assertNotIn(101,[r["round_id"] for r in ready])
        ready,_=g.process(rows([10,1.5,2]))
        self.assertIn(101,[r["round_id"] for r in ready])
    def test_blank_snapshot_drops_stability(self):
        g=FinalityGuard();g.process(rows([10,1]));g.process([])
        self.assertEqual(g.process(rows([10,1]))[0],[])

if __name__=="__main__":unittest.main()
