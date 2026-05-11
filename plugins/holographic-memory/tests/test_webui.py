import unittest
import tempfile
import os
import sys
import json
import urllib.request
import threading
from http.server import HTTPServer

# Add parent dir to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from webui import Handler
from store import MemoryStore

class MockServer:
    def __init__(self, db_path, port=8889):
        self.port = port
        self.store = MemoryStore(db_path=db_path)
        self.store._init_db()
        Handler.store = self.store
        self.server = HTTPServer(('localhost', self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.store.close()
        self.thread.join()

class TestWebUIE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_fd, cls.db_path = tempfile.mkstemp()
        cls.server = MockServer(db_path=cls.db_path, port=8889)
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        os.close(cls.db_fd)
        os.unlink(cls.db_path)

    def request(self, method, path, data=None):
        url = f"http://localhost:8889{path}"
        headers = {}
        body = None
        if data is not None:
            body = json.dumps(data).encode('utf-8')
            headers['Content-Type'] = 'application/json'
            
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as response:
                res_body = response.read().decode('utf-8')
                if response.headers.get('Content-Type') == 'application/json':
                    return response.status, json.loads(res_body)
                return response.status, res_body
        except urllib.error.HTTPError as e:
            res_body = e.read().decode('utf-8')
            try:
                return e.code, json.loads(res_body)
            except:
                return e.code, res_body

    def test_api_lifecycle(self):
        """Test the full lifecycle of facts through the HTTP API."""
        # 1. Start with empty facts
        status, data = self.request("GET", "/api/facts")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["facts"]), 0)

        # 2. Create a fact
        status, data = self.request("POST", "/api/facts", {
            "content": "API tests are running successfully",
            "category": "testing",
            "tags": "api,e2e"
        })
        self.assertEqual(status, 200)
        self.assertIn("fact_id", data)
        fact_id = data["fact_id"]

        # 3. Verify creation
        status, data = self.request("GET", "/api/facts")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["facts"]), 1)
        self.assertEqual(data["facts"][0]["content"], "API tests are running successfully")

        # 4. Search for the fact
        status, data = self.request("GET", "/api/search?q=API")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["facts"]), 1)
        self.assertIn("API", data["facts"][0]["content"])

        # 5. Provide feedback
        status, data = self.request("POST", f"/api/facts/{fact_id}/feedback", {"helpful": True})
        self.assertEqual(status, 200)
        self.assertIn("new_trust", data)
        self.assertGreater(data["new_trust"], 0.5)

        # 6. Update the fact
        status, data = self.request("PUT", f"/api/facts/{fact_id}", {
            "content": "API tests are passing"
        })
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))

        # Verify update
        status, data = self.request("GET", "/api/facts")
        self.assertEqual(data["facts"][0]["content"], "API tests are passing")

        # 7. Check stats
        status, data = self.request("GET", "/api/stats")
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 1)

        # 8. Delete the fact
        status, data = self.request("DELETE", f"/api/facts/{fact_id}")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))

        # Verify deletion
        status, data = self.request("GET", "/api/facts")
        self.assertEqual(len(data["facts"]), 0)

if __name__ == '__main__':
    unittest.main()