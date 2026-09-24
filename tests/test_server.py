import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen

from recorder import Application,make_server

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=Application(Path(self.tmp.name)/"data")
        self.server=make_server(self.app,0)
        self.base=f"http://127.0.0.1:{self.server.server_port}"
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.app.close();self.tmp.cleanup()
    def request(self,path,body=None,auth=True,headers=None):
        h={"X-Recorder-Token":self.app.token} if auth else {}
        if headers:h.update(headers)
        data=None
        if body is not None:
            h["Content-Type"]="application/json";data=json.dumps(body).encode()
        try:
            response=urlopen(Request(self.base+path,data=data,headers=h),timeout=10)
        except HTTPError as e:
            return e.code,e.read()
        return response.status,response.read()
    def test_shutdown_requires_confirmation(self):
        status,_=self.request('/api/shutdown', {"confirmed": False})
        self.assertEqual(status,400)
        status,_=self.request('/api/status')
        self.assertEqual(status,200)
    def test_shutdown_requires_authentication(self):
        status,_=self.request('/api/shutdown', {"confirmed": True},auth=False)
        self.assertEqual(status,403)
    def test_api_needs_token(self):
        status,_=self.request('/api/status',auth=False)
        self.assertEqual(status,403)
    def test_cross_origin_rejected(self):
        status,_=self.request('/api/import',{"csv":"round_id,crash\n1,2","confirmed":True},headers={"Origin":"https://evil.example"})
        self.assertEqual(status,403)
    def test_bad_host_rejected(self):
        status,_=self.request('/',headers={"Host":"evil.example"})
        self.assertEqual(status,403)
    def test_status_and_static_dashboard(self):
        status,data=self.request('/api/status')
        self.assertEqual(status,200);self.assertEqual(json.loads(data)["report"]["total_rounds"],0)
        status,data=self.request('/',auth=False)
        self.assertEqual(status,200);self.assertIn(b'Crash Round Recorder',data)
    def test_csv_import_and_download(self):
        status,_=self.request('/api/import',{"csv":"round_id,crash\n100,10\n101,1\n102,1\n103,1\n104,2\n105,10","confirmed":True})
        self.assertEqual(status,200)
        _,data=self.request('/api/status')
        self.assertEqual(json.loads(data)["report"]["complete_windows"],1)
        status,data=self.request('/api/rounds.csv')
        self.assertEqual(status,200);self.assertIn(b'100,10.00',data)
    def test_import_requires_confirmation(self):
        status,_=self.request('/api/import',{"csv":"round_id,crash\n100,10","confirmed":False})
        self.assertEqual(status,400)
    def test_approved_vault_export(self):
        vault=Path(self.tmp.name)/"vault";vault.mkdir()
        status,_=self.request('/api/settings',{"vault":str(vault)})
        self.assertEqual(status,200)
        status,_=self.request('/api/export',{})
        self.assertEqual(status,200)
        self.assertTrue((vault/'Crash Round Research/ethercrash Dashboard.md').is_file())
    def test_invalid_source_and_unapproved_capture(self):
        status,_=self.request('/api/settings',{"url":"https://evil.example/"})
        self.assertEqual(status,400)
        status,_=self.request('/api/capture/approve',{"confirmed":True,"preview_version":0})
        self.assertEqual(status,400)

if __name__=='__main__':unittest.main()
