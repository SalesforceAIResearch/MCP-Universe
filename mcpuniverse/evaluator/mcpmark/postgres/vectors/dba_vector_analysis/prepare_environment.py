"""
Environment preparation script for Vector Database DBA Analysis task.

This script imports and uses the shared vector database setup utilities.
"""

import sys
import logging
from pathlib import Path

# Add the vectors directory to import the shared utilities
sys.path.append(str(Path(__file__).resolve().parents[1]))

from vectors_setup import prepare_vector_environment

logger = logging.getLogger(__name__)


def prepare_environment():
    """Main function to prepare the vector database environment."""
    prepare_vector_environment()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    prepare_environment()