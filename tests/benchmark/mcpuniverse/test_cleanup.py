import pytest
import unittest
from mcpuniverse.benchmark.cleanups import github_delete_repository


class TestTaskCleanup(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test_github_delete_repository(self):
        print(await github_delete_repository(owner="yangwenz", repo="temp"))


if __name__ == "__main__":
    unittest.main()
