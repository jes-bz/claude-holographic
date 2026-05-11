import unittest
import tempfile
import os
import sys

# Add parent dir to path so we can import the plugin modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from store import MemoryStore
from retrieval import FactRetriever
import holo

class TestMemoryE2E(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        # Initialize store with a smaller dimension for faster tests
        self.store = MemoryStore(db_path=self.db_path, hrr_dim=256)
        self.store._init_db()
        self.retriever = FactRetriever(self.store, hrr_dim=256)

    def tearDown(self):
        self.store.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_store_and_retrieve_lifecycle(self):
        """End to end test of adding, searching, updating, and removing facts."""
        # 1. Add facts
        fact_id1 = self.store.add_fact(
            content="The system should use SQLite for local storage.",
            category="architecture",
            tags="sqlite,db",
            project_path="/test/path"
        )
        self.assertTrue(fact_id1 > 0)

        fact_id2 = self.store.add_fact(
            content="The UI is built with React and Tailwind.",
            category="frontend",
            tags="react,tailwind"
        )
        self.assertTrue(fact_id2 > 0)

        # 2. Search facts (FTS and tags)
        results = self.retriever.search("SQLite storage")
        self.assertGreaterEqual(len(results), 1)
        self.assertIn("SQLite", results[0]["content"])

        # 3. Update fact
        updated = self.store.update_fact(
            fact_id1,
            content="The system must use SQLite for local storage.",
            tags="sqlite,db,storage"
        )
        self.assertTrue(updated)
        
        # Verify update
        facts = self.store.list_facts(category="architecture")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["content"], "The system must use SQLite for local storage.")
        self.assertEqual(facts[0]["tags"], "sqlite,db,storage")

        # 4. Record feedback
        fb = self.store.record_feedback(fact_id1, helpful=True)
        self.assertEqual(fb["helpful_count"], 1)
        self.assertGreater(fb["new_trust"], 0.5)

        # 5. Remove fact
        removed = self.store.remove_fact(fact_id2)
        self.assertTrue(removed)
        
        # Verify removal
        remaining = self.store.list_facts()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["fact_id"], fact_id1)

    def test_holo_extraction(self):
        """Test the logic that extracts facts from conversation transcripts."""
        messages = [
            {"role": "user", "content": "Please remember that I prefer a dark theme."},
            {"role": "assistant", "content": "I will note that you prefer a dark theme."},
            {"role": "user", "content": "The database needs to be normalized."},
            {"role": "assistant", "content": "I'll keep in mind that the database needs to be normalized."}
        ]
        
        facts = holo._extract_with_regex(messages)
        self.assertGreaterEqual(len(facts), 1)
        
        # Should extract user preferences and assistant acknowledgements based on regex rules
        contents = [f[0] for f in facts]
        self.assertTrue(any("dark theme" in c for c in contents))

if __name__ == '__main__':
    unittest.main()