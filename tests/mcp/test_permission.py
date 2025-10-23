import unittest

from mcpuniverse.mcp.permission import ToolPermission, check_permissions


class TestPermission(unittest.TestCase):

    def test_1(self):
        permission = ToolPermission(
            tool="list_actions",
            action="reject"
        )
        result = permission.match(tool_name="list_actions")
        self.assertEqual(result, "reject")
        result = permission.match(tool_name="list_action")
        self.assertEqual(result, None)

        permission = ToolPermission(
            tool="list_*",
            action="reject"
        )
        result = permission.match(tool_name="list_actions")
        self.assertEqual(result, "reject")

    def test_2(self):
        permission = ToolPermission(
            tool="list_actions",
            arguments={"folder": "abc"},
            action="reject"
        )
        result = permission.match(
            tool_name="list_actions",
            arguments={"folder": "ab"}
        )
        self.assertEqual(result, None)
        result = permission.match(
            tool_name="list_actions",
            arguments={"folder": "abcd"}
        )
        self.assertEqual(result, None)
        result = permission.match(
            tool_name="list_actions",
            arguments={"folder": "abc"}
        )
        self.assertEqual(result, "reject")

        permission = ToolPermission(
            tool="list_actions",
            arguments={"folder": "abc*"},
            action="reject"
        )
        result = permission.match(
            tool_name="list_actions",
            arguments={"folder": "abcd"}
        )
        self.assertEqual(result, "reject")

    def test_3(self):
        status = check_permissions(
            permissions=[ToolPermission(
                tool="list_actions",
                action="reject"
            )],
            tool_name="list_actions"
        )
        self.assertEqual(status.approved, False)

        status = check_permissions(
            permissions=[ToolPermission(
                tool="list_actions",
                action="allow"
            )],
            tool_name="list_actions"
        )
        self.assertEqual(status.approved, True)


if __name__ == "__main__":
    unittest.main()
