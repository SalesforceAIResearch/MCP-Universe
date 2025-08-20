"""
Evaluation functions for Github tasks
"""
# pylint: disable=broad-exception-caught,unused-argument
import io
import csv
import json
from typing import Optional, Literal, List, Tuple
from mcpuniverse.evaluator.functions import compare_func
from mcpuniverse.mcp.manager import MCPManager


##################################################################################
# Utils Function for Github
##################################################################################
async def github__check_repository(query: str, **kwargs):
    """Check whether a Github repository exists."""
    manager = MCPManager(context=kwargs.get("context", None))

    # search repositories in github MCP might be crashed, so we need to catch the error
    try:
        output = await manager.execute(
            server_name="github",
            tool_name="search_repositories",
            arguments={"query": query},
            transport="stdio"
        )
    except Exception as e:
        print(f"Error searching repositories: {e}")
        return None
    if output.isError:
        return None
    json_obj = json.loads(output.content[0].text)
    return json_obj


async def github__get_file_contents(owner: str, repo: str, path: str, branch: Optional[str] = None, **kwargs):
    """Get the content of a file, return none if not exist."""
    manager = MCPManager(context=kwargs.get("context", None))
    args = {
        "owner": owner,
        "repo": repo,
        "path": path
    }
    if branch:
        args["ref"] = branch

    # get file contents in github MCP might be crashed, so we need to catch the error
    try:
        output = await manager.execute(
            server_name="github",
            tool_name="get_file_contents",
            arguments=args,
            transport="stdio"
        )
    except Exception as e:
        print(f"Error getting file contents: {e}")
        return None
    if output.isError:
        return None
    return output.content[1].resource.text

async def github__list_branches(owner: str, repo: str, **kwargs):
    """List the branches of a repository."""
    manager = MCPManager(context=kwargs.get("context", None))
    args = {
        "owner": owner,
        "repo": repo
    }

    # list branches in github MCP might be crashed, so we need to catch the error
    try:
        output = await manager.execute(
            server_name="github",
            tool_name="list_branches",
            arguments=args,
            transport="stdio"
        )
    except Exception as e:
        print(f"Error listing branches: {e}")
        return None
    if output.isError:
        return None
    json_obj = json.loads(output.content[0].text)
    return json_obj

async def github__list_pull_requests(owner: str, repo: str, base: str, head: str, **kwargs) -> Optional[List]:
    """List the PRs from head to base."""
    manager = MCPManager(context=kwargs.get("context", None))
    args = {
        "owner": owner,
        "repo": repo,
        "base": base,
        "head": head
    }

    # list pull requests in github MCP might be crashed, so we need to catch the error
    try:
        output = await manager.execute(
            server_name="github",
            tool_name="list_pull_requests",
            arguments=args,
            transport="stdio"
        )
    except Exception as e:
        print(f"Error listing pull requests: {e}")
        return None
    if output.isError:
        return None
    json_obj = json.loads(output.content[0].text)
    return json_obj


async def github__list_issues(owner: str, repo: str,
                              state: Optional[Literal['open', 'closed', 'all']] = None,
                              labels: Optional[List[str]] = None, **kwargs):
    """List the issues"""
    manager = MCPManager(context=kwargs.get("context", None))
    args = {
        "owner": owner,
        "repo": repo,
        "perPage": 100
    }
    if state:
        args["state"] = state
    if labels:
        args["labels"] = labels

    json_obj = []
    for page_number in range(1, 40):
        # Assume the number of issues page is at most 40
        # the total number of issues is at most 4000
        try:
            args["page"] = page_number

            # list issues in github MCP might be crashed, so we need to catch the error
            try:
                output = await manager.execute(
                    server_name="github",
                    tool_name="list_issues",
                    arguments=args,
                    transport="stdio"
                )
            except Exception as e:
                print(f"Error listing issues: {e}")
                return None
            if output.isError:
                return None
            current_page_json = json.loads(output.content[0].text)
            if len(current_page_json) == 0:
                break
            json_obj.extend(current_page_json)
        except (json.JSONDecodeError, IndexError, KeyError) as e:
            print(f"Error parsing issues response on page {page_number}: {e}")
            break
        except Exception as e:
            print(f"Unexpected error fetching issues on page {page_number}: {e}")
            break
    return json_obj


async def github__get_issue_comments(owner: str, repo: str, issue_number: int, **kwargs):
    """Get the comments of an issue."""
    manager = MCPManager(context=kwargs.get("context", None))
    args = {
        "owner": owner,
        "repo": repo,
        "issue_number": issue_number
    }
    try:
        output = await manager.execute(
            server_name="github",
            tool_name="get_issue_comments",
            arguments=args,
            transport="stdio"
        )
    except Exception as e:
        print(f"Error getting issue comments: {e}")
        return None
    if output.isError:
        return None
    json_obj = json.loads(output.content[0].text)
    return json_obj


##################################################################################
# Evaluation functions
##################################################################################

@compare_func(name="github.check_repository")
async def github_check_repository(x: dict, *args, **kwargs) -> Tuple[bool, str]:
    """Check whether a Github repository exists."""
    _, query = args
    repos = await github__check_repository(query, **kwargs)
    if repos is None or repos['total_count'] == 0:
        return False, "the repository doesn't exist"

    full_names = [repo['full_name'] for repo in repos['items']]
    if query in full_names:
        return True, ""
    return False, "the repository doesn't exist"


@compare_func(name="github.check_branches_exist")
async def github_check_branches_exist(x: dict, *args, **kwargs) -> Tuple[bool, str]:
    """Check whether branches exists."""
    _, op_args = args
    branches = await github__list_branches(op_args['owner'], op_args['repo'], **kwargs)
    if branches is None:
        return False, "the branches don't exist"
    branches_name = [branch['name'] for branch in branches]
    for branch in op_args['branches']:
        if branch not in branches_name:
            return False, f"the branch {branch} doesn't exist"
    return True, ""


@compare_func(name="github.check_file_content")
async def github_check_file_content(x: dict, *args, **kwargs) -> Tuple[bool, str]:
    """Check if file content is valid."""
    value, op_args = args

    resp = await github__get_file_contents(
            op_args['owner'], op_args['repo'], op_args['path'], op_args['branch'], **kwargs)

    expected_file_content = ""
    if isinstance(value, str):
        expected_file_content = value
    elif isinstance(value, dict):
        expected_file_content = await github__get_file_contents(
            value['owner'], value['repo'], value['path'], value['branch'], **kwargs)

    if resp is None:
        return False, "the file content is not found"
    if expected_file_content == "":
        return False, "the expected file content is not found"

    if not expected_file_content.strip() == resp.strip():
        return False, "the file content is incorrect!"
    return True, ""


@compare_func(name="github.check_file_not_exist")
async def github_check_file_not_exist(x: dict, *args, **kwargs) -> Tuple[bool, str]:
    """Check if file does not exist."""
    _, op_args = args
    resp = await github__get_file_contents(op_args['owner'], op_args['repo'],
                                           op_args['path'], op_args['branch'], **kwargs)
    if resp:
        return False, f"the file exists!\n## response:\n{resp}"
    return True, ""


@compare_func(name="github.check_file_exist")
async def github_check_file_exist(x: dict, *args, **kwargs) -> Tuple[bool, str]:
    """Check if file exists."""
    _, op_args = args
    resp = await github__get_file_contents(op_args['owner'], op_args['repo'],
                                           op_args['path'], op_args['branch'], **kwargs)
    if not resp:
        return False, f"the file doesn't exist!\n## response:\n{resp}"
    return True, ""


@compare_func(name="github.check_pull_request")
async def github_check_pull_request(x: dict, *args, **kwargs) -> Tuple[bool, str]:
    """Check if PRs are valid."""
    _, op_args = args
    prs = await github__list_pull_requests(
        op_args['owner'], op_args['repo'], op_args['base'], op_args['head'], **kwargs)

    if prs:
        # Only check title/body if they exist in op_args
        for pr in prs:
            title_match = True
            body_match = True
            if 'title' in op_args:
                title_match = pr.get('title') == op_args['title']
            if 'body' in op_args:
                body_match = pr.get('body') == op_args['body']
            if title_match and body_match:
                return True, ""
        return False, "the PR content is incorrect!"
    return False, "the PR doesn't exist"


@compare_func(name="github.check_file_content_and_issue_count")
async def github_check_file_content_and_issue_count(x: dict, *args, **kwargs) -> Tuple[bool, str]:
    """Check if CSV files are valid and the number of rows matches the number of issues."""

    async def _get_groundtruth_repo_list(repo_owner, repo_name, issue_state, issue_labels):
        repo_list = await github__check_repository(f"user:{repo_owner} {repo_name} in:name",
                                                   **kwargs)
        if repo_list is None:
            return None
        ret = {}
        for repo in repo_list["items"]:
            repo_full_name = repo["full_name"]
            issues = await github__list_issues(repo["owner"]["login"], repo["name"],
                                               labels=issue_labels, state=issue_state)
            ret[repo_full_name] = len(issues)
        return ret

    def _get_file_content_to_dict(file_content, **op_args):
        file_type = op_args['file_type']
        if file_type == "csv":
            csv_file = io.StringIO(file_content)
            reader = csv.DictReader(csv_file)
            return_repo_list = {}
            for row in reader:
                csv_columns = op_args['csv_columns']
                assert len(csv_columns) == 2, "the number of columns should be 2"
                repository_name = row[csv_columns[0]]
                return_repo_list[repository_name] = int(row[csv_columns[1]])
            return return_repo_list
        if file_type == "json":
            return json.loads(file_content)
        raise ValueError(f"Unsupported file type: {file_type}")

    _, op_args = args


    # get the groundtruth repo list
    gt_repo_list = await _get_groundtruth_repo_list(
        op_args['search_repo_owner'], op_args['search_repo_name'],
        op_args['issue_state'], op_args['issue_labels'])

    if gt_repo_list is None:
        return False, "the groundtruth repo list is not found"

    # get the csv file content
    resp = await github__get_file_contents(
        op_args['owner'], op_args['repo'], op_args['path'], op_args['branch'], **kwargs)

    if resp is None:
        return False, "the file content is not found"

    return_repo_list = _get_file_content_to_dict(resp, **op_args)

    # check if the return_repo_list is the same as the gt_repo_list
    if not return_repo_list == gt_repo_list:
        return False, (
            "the return_repo_list is not the same as the gt_repo_list!\n"
            f"## response:\n{return_repo_list} \n"
            f"## expected:\n{gt_repo_list}"
        )
    return True, ""


@compare_func(name="github.file_content_include")
async def github_file_content_include(x: dict, *args, **kwargs) -> Tuple[bool, str]:
    """Check if file content include some strings."""
    value, op_args = args
    resp = await github__get_file_contents(
        op_args['owner'], op_args['repo'], op_args['path'], op_args['branch'], **kwargs)
    file_path = f"{op_args['owner']}/{op_args['repo']}/{op_args['branch']}/{op_args['path']}"
    if resp:
        if value is None:
            return True, ""
        for str0 in value:
            if str0 not in resp:
                return False, f"{resp} doesn't include {str0}"
        return True, ""
    return False, f"the file {file_path} doesn't exist"


@compare_func(name="github.check_repository_with_fewest_issues")
async def github_check_repository_with_fewest_issues(x: dict, *args, **kwargs) -> Tuple[bool, str]:
    """Check if file content is valid and the number of issues is the fewest."""
    _, op_args = args
    repos = op_args['repos']
    owner = op_args['owner']
    # find the repo with the fewest issues
    fewest_issues_repo_name = None
    fewest_issues_count = float('inf')
    for repo in repos:
        repo_owner, repo_name = repo.split('/')
        issues = await github__list_issues(repo_owner, repo_name, state=op_args['issue_state'])
        if issues is None:
            return False, "the issues are not found"
        if len(issues) < fewest_issues_count:
            fewest_issues_count = len(issues)
            fewest_issues_repo_name = repo_name
    repos_check = await github__check_repository(f"repo:{owner}/{fewest_issues_repo_name} fork:true")

    if repos_check is None or repos_check['total_count'] == 0:
        return False, "the repository doesn't exist"
    full_names = [repo['full_name'] for repo in repos_check['items']]
    if f"{owner}/{fewest_issues_repo_name}" in full_names:
        return True, ""
    return False, "the repository doesn't exist"


@compare_func(name="github.check_file_content_with_fewest_issues")
async def github_check_file_content_with_fewest_issues(x: dict, *args, **kwargs) -> Tuple[bool, str]:
    """Check if file content is valid and the number of issues is the fewest."""
    _, op_args = args
    repos = op_args['repos']
    owner = op_args['owner']
    # find the repo with the fewest issues
    fewest_issues_repo_name = None
    fewest_issues_count = float('inf')
    fewest_issues_repo_id = None
    for repo_id, repo in enumerate(repos):
        repo_owner, repo_name = repo.split('/')
        issues = await github__list_issues(repo_owner, repo_name, state=op_args['issue_state'])
        if issues is None:
            return False, "the issues are not found"
        if len(issues) < fewest_issues_count:
            fewest_issues_count = len(issues)
            fewest_issues_repo_name = repo_name
            fewest_issues_repo_id = repo_id
    repos_check = await github__check_repository(
        f"repo:{owner}/{fewest_issues_repo_name} fork:true"
    )

    if repos_check is None or repos_check['total_count'] == 0:
        return False, "the repository doesn't exist"

    full_names = [repo['full_name'] for repo in repos_check['items']]
    if f"{owner}/{fewest_issues_repo_name}" not in full_names:
        return False, "the repository doesn't exist"

    resp = await github__get_file_contents(
        owner, fewest_issues_repo_name, op_args['path'], op_args['branch'], **kwargs)
    value = op_args['file_content'][fewest_issues_repo_id]
    if resp and value in resp:
        return True, ""
    return False, f"Content '{value}' is not found in the file"


@compare_func(name="github.check_number_of_issues")
async def github_check_number_of_issues(x: dict, *args, **kwargs) -> Tuple[bool, str]:
    """Check the github issues"""

    async def _filter(issue: dict, condition: dict):
        if "title" in condition and condition["title"] is not None:
            if issue["title"] != condition["title"]:
                return False
        if "labels" in condition and condition["labels"] is not None:
            labels = [label['name'] for label in issue['labels']]
            if not all(ele in labels for ele in condition["labels"]):
                return False
        if "comments" in condition and condition["comments"] is not None:
            comments = await github__get_issue_comments(op_args['owner'], op_args['repo'], issue['number'])
            if not any(comment['body'] == condition["comments"] for comment in comments):
                return False
        return True

    value, op_args = args
    title = op_args.get('title', None)
    labels = op_args.get('labels', None)
    state = op_args.get('state', None)
    comments = op_args.get('comments', None)
    if comments and "[repo owner name]" in comments:
        comments = comments.replace("[repo owner name]", op_args['owner'])

    issues = await github__list_issues(
        op_args['owner'], op_args['repo'], state=state, labels=labels
    )
    if issues is None:
        return False, "the issues are not found"

    filter_args = {
        "title": title,
        "labels": labels,
        "comments": comments
    }
    filtered_issues = [issue for issue in issues if await _filter(issue, filter_args)]
    if len(filtered_issues) == value:
        return True, ""
    return False, (
        "the number of filtered issues [title:\"{title}\", labels:{labels}] is wrong\n"
        f"## response:\n{len(filtered_issues)} \n"
        f"## expected:\n{value}"
    )
