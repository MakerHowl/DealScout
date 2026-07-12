from abc import ABC, abstractmethod
from typing import List, Dict, Any

class NotificationService(ABC):
    @abstractmethod
    def send_test(self, settings: dict) -> bool:
        """
        Send a test message using the given settings dictionary.
        Returns True if successful, False otherwise.
        """
        pass

    @abstractmethod
    def send_digest(self, settings: dict, market_name: str, offers: List[Dict[str, Any]]) -> bool:
        """
        Send a digest notification of matching offers.
        Returns True if successful, False otherwise.
        """
        pass
