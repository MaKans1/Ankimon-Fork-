import logging

logging.disable(logging.CRITICAL)

import os
import sys
PROJECT_PATH = os.getcwd()
SOURCE_PATH = os.path.join(
    PROJECT_PATH,"poke-engine"
)
sys.path.append(SOURCE_PATH)