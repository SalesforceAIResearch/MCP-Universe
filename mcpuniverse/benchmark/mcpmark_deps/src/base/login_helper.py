from abc import ABC, abstractmethod


class BaseLoginHelper(ABC):
    """Abstract base class for login helpers."""

    def __init__(self):
        pass

    @abstractmethod
    def login(self, **kwargs):
        pass
