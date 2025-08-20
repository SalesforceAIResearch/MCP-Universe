import os
import unittest
import datetime
from mcpuniverse.app.utils.token import paseto_encode, paseto_decode


class TestPasetoToken(unittest.TestCase):

    def setUp(self):
        os.environ["TOKEN_SYMMETRIC_KEY"] = "123456789"

    def test(self):
        data = {"a": 1, "b": 2, "c": datetime.datetime.now().timestamp()}
        token = paseto_encode(data)
        self.assertDictEqual(data, paseto_decode(token))


if __name__ == "__main__":
    unittest.main()
