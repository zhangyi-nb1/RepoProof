import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from starter_project import PROJECT_NAME

class StarterProjectTests(unittest.TestCase):
    def test_project_name_is_present(self):
        self.assertTrue(PROJECT_NAME.strip())
