import os
import tempfile
import atexit
import shutil

# 1. Create temporary directories for the test session
temp_data = tempfile.mkdtemp(prefix="p2p_data_")
temp_state = tempfile.mkdtemp(prefix="p2p_state_")

# Clean up temp directories when tests finish
atexit.register(lambda: shutil.rmtree(temp_data, ignore_errors=True))
atexit.register(lambda: shutil.rmtree(temp_state, ignore_errors=True))

# 2. STRICTLY set environment variables BEFORE any backend imports happen
os.environ["P2P_DATA_DIR"] = temp_data
os.environ["P2P_STATE_DIR"] = temp_state
os.environ["LLM_MODE"] = "offline"
os.environ["GEMINI_API_KEY"] = ""