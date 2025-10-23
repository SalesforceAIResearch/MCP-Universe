"""
GitHub Token Pool Manager
=========================

Simple round-robin token pool for distributing API requests across multiple tokens
to avoid rate limit issues.
"""

from typing import List
from src.logger import get_logger

logger = get_logger(__name__)


class GitHubTokenPool:
    """
    Manages a pool of GitHub tokens with round-robin selection.
    """
    
    def __init__(self, tokens: List[str]):
        """
        Initialize token pool.
        
        Args:
            tokens: List of GitHub personal access tokens
        """
        if not tokens:
            raise ValueError("Token pool must contain at least one token")
            
        self.tokens = tokens
        self.current_index = 0
        logger.info(f"Initialized GitHub token pool with {len(tokens)} token(s)")
    
    def get_next_token(self) -> str:
        """
        Get the next token in round-robin fashion.
        
        Returns:
            The next GitHub token to use
        """
        token = self.tokens[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.tokens)
        return token
    
    def get_current_token(self) -> str:
        """
        Get the current token without advancing the index.
        
        Returns:
            The current GitHub token
        """
        return self.tokens[self.current_index]
    
    @property
    def pool_size(self) -> int:
        """Get the number of tokens in the pool."""
        return len(self.tokens)