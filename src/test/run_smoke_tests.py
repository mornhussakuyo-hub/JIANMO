from __future__ import annotations

import sys
import unittest


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover("src/test", pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
