#!/usr/bin/env python3
import sys
from pathlib import Path
import unittest

def main():
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / 'src'))
    suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1

if __name__ == '__main__':
    raise SystemExit(main())
