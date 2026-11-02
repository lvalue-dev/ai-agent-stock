import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("KIS_APP_KEY", "test-key")
os.environ.setdefault("KIS_APP_SECRET", "test-secret")
