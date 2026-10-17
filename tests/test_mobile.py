import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

class MobileDownloads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        threading.Thread(target=cls.http.serve_forever,daemon=True).start()
        cls.base='http://127.0.0.1:'+str(cls.http.server_port)
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close()
    def test_mobile_page_and_script_are_public(self):
        for path,content in [('/mobile',b'Download Android app'),('/mobile.js',b'pending deployment')]:
            with urllib.request.urlopen(self.base+path) as response:
                self.assertEqual(response.status,200)
                self.assertIn(content,response.read())
                self.assertIn("script-src 'self'",response.headers['Content-Security-Policy'])
    def test_apk_signature_and_download_checksum(self):
        apk=server.ROOT/'static/downloads/olamide-medical.apk'
        if not apk.exists():self.skipTest('Build the APK first')
        with urllib.request.urlopen(self.base+'/downloads/olamide-medical.apk') as response:
            data=response.read()
            self.assertEqual(response.headers['Content-Type'],'application/vnd.android.package-archive')
            self.assertIn('attachment;',response.headers['Content-Disposition'])
            self.assertEqual(int(response.headers['Content-Length']),len(data))
            self.assertEqual(data[:2],b'PK')
        with urllib.request.urlopen(self.base+'/downloads/olamide-medical.apk.sha256') as response:
            self.assertEqual(response.read().decode().split()[0],hashlib.sha256(data).hexdigest())
    def test_download_allowlist(self):
        for path in ['/downloads/../server.py','/downloads/private.jks','/downloads/other.apk']:
            with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(self.base+path)
            self.assertEqual(caught.exception.code,404)

if __name__=='__main__':unittest.main()
