"""
Environment preparation script for Vector Database DBA Analysis task.

This script imports and uses the shared vector database setup utilities.
"""

import sys
import logging
from pathlib import Path

# Add the current directory (postgres_verification_files) to import the shared utilities
# In the new structure, vectors_setup.py is in the same directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

from vectors_setup import prepare_vector_environment

logger = logging.getLogger(__name__)


def prepare_environment():
    """Main function to prepare the vector database environment."""
    prepare_vector_environment()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    prepare_environment()