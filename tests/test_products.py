"""产品块的块内补齐：存在性检查路由、重算与状态查询、封账、异步转换与工作空间级检查。"""

import json

import pytest

from test_client import service
from rqamsh.errors import HarnessError


def _catalog(products, units=None, groups=()):
    """按目录构建顺序生成响应：产品列表与逐个详情、组列表与逐个详情、资产单元。"""
    responses = [(200, {"products": list(products)})]
    for row in products:
        responses.append((200, row))
    responses.append((200, {"product_groups": list(groups)}))
    for row in groups:
        responses.append((200, row))
    responses.append((200, units or []))
    return responses


_OWN = {"id": "p1", "name": "own", "user_id": 1}


def test_field_exists_routes_account_name_to_dedicated_endpoint(service):
    """四个字段各自命中正确端点；账号名称必须走查 accounts.name 的专用路由。"""
    client, state = service
    for kwargs, endpoint in (
        ({"name": "n"}, "/api/rqams/v2/products:is_field_exists?name=n"),
        ({"full_name": "f"}, "/api/rqams/v2/products:is_field_exists?full_name=f"),
        ({"fund_code": "c"}, "/api/rqams/v2/products:is_field_exists?fund_code=c"),
        ({"account_name": "a"}, "/api/rqams/v2/products:account_name_exists?account_name=a"),
    ):
        state["responses"] = [(200, {"exists": False})]
        assert client.products.field_exists(**kwargs) == {"exists": False}
        assert state["requests"][-1][1] == endpoint


def test_field_exists_requires_exactly_one_field(service):
    """零个或多个字段必须在请求前失败，不能被服务端按固定顺序静默取第一个。"""
    client, state = service
    for kwargs in ({}, {"name": "n", "fund_code": "c"}):
        with pytest.raises(HarnessError) as error:
            client.products.field_exists(**kwargs)
        assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_enable_shares_posts_three_mappings_and_waits_for_task(service):
    """份额转换提交三段映射体，并按 task_id 轮询到终态。"""
    client, state = service
    state["responses"] = _catalog([_OWN]) + [(202, {"task_id": "task-a"}), (200, {"status": "SUCCESS", "progress": 1, "data": None})]
    result = client.products.enable_shares(
        "own", {"A": {"effective_date": "2026-01-01"}}, {"ce1": {"A": 100.0}}, {"ue1": {"A": 10.0}}
    )
    assert result == {"status": "SUCCESS", "progress": 1, "data": None}
    submit, poll = state["requests"][-2], state["requests"][-1]
    assert (submit[0], submit[1]) == ("POST", "/api/rqams/v2/products/p1:enable_shares")
    assert json.loads(submit[2]) == {
        "shares": {"A": {"effective_date": "2026-01-01"}},
        "custodian_events": {"ce1": {"A": 100.0}},
        "unit_events": {"ue1": {"A": 10.0}},
    }
    assert poll[0] == "GET" and "task_id=task-a" in poll[1] and poll[2] == b""


def test_create_example_polls_the_get_endpoint(service):
    """范例产品创建没有入参，首调 GET 返回 202 后按 task_id 轮询。"""
    client, state = service
    state["responses"] = [(202, {"task_id": "task-e"}), (200, {"status": "SUCCESS", "progress": 1, "data": ["示例产品"]})]
    assert client.products.create_example() == {"status": "SUCCESS", "progress": 1, "data": ["示例产品"]}
    assert [item[0] for item in state["requests"]] == ["GET", "GET"]
    assert state["requests"][0][1] == "/api/rqams/v2/products:create_example"


def test_valuation_report_missing_dates_filters_unreadable_products(service):
    """工作空间级缺表汇总只返回目录里可见的产品（详情读不到的他人产品被排除）。"""
    client, state = service
    rows = [
        {"product_id": "p1", "product_name": "own", "missing_date_count": 2},
        {"product_id": "p2", "product_name": "hidden", "missing_date_count": 5},
    ]
    state["responses"] = [
        (200, rows),
        (200, {"products": [{"id": "p1", "name": "own", "user_id": 1}, {"id": "p2", "name": "hidden", "user_id": 2}]}),
        (200, {"id": "p1", "name": "own", "user_id": 1}),
        (403, {"message": "无权访问"}),
        (200, {"product_groups": []}), (200, []),
    ]
    assert client.products.valuation_report_missing_dates() == [rows[0]]
    assert any(item[1] == "/api/rqams/v2/products:valuation_report_missing_date" for item in state["requests"])


def test_uploaded_file_hashes_resolves_ids_without_permission_lookup(service):
    """解析只读目录，不额外查询权限：他人产品照常解析，请求按解析后的 ID 提交。"""
    client, state = service
    state["responses"] = _catalog([_OWN]) + [(200, [{"product_id": "p1", "hash_list": ["h1"]}])]
    assert client.products.uploaded_file_hashes(["own"], "trade") == [{"product_id": "p1", "hash_list": ["h1"]}]
    assert json.loads(state["requests"][-1][2]) == {"product_ids": ["p1"], "file_type": "trade"}
    state["requests"].clear()
    state["responses"] = _catalog([_OWN, {"id": "p2", "name": "shared", "user_id": 2}]) + [
        (200, [{"product_id": "p2", "hash_list": []}]),
    ]
    assert client.products.uploaded_file_hashes(["shared"], "trade") == [{"product_id": "p2", "hash_list": []}]
    assert json.loads(state["requests"][-1][2]) == {"product_ids": ["p2"], "file_type": "trade"}


def test_uploaded_file_hashes_rejects_unknown_file_type(service):
    """未知 file_type 在取目录前失败。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.products.uploaded_file_hashes(["own"], "dividend")
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_closing_entry_put_and_delete_use_distinct_semantics(service):
    """封账写字段、解封删除字段，两者都是空响应。"""
    client, state = service
    state["responses"] = _catalog([_OWN]) + [(200, b"")]
    assert client.products.set_closing_entry("own", "2026-08-31") is None
    request = state["requests"][-1]
    assert (request[0], request[1]) == ("PUT", "/api/rqams/v2/products/p1/closing_entry")
    assert json.loads(request[2]) == {"closing_date": "2026-08-31"}
    state["responses"] = _catalog([_OWN]) + [(200, b"")]
    assert client.products.clear_closing_entry("own") is None
    assert (state["requests"][-1][0], state["requests"][-1][1]) == ("DELETE", "/api/rqams/v2/products/p1/closing_entry")


def test_recompute_submits_product_ids_and_optional_start_date(service):
    """重算按产品 ID 数组提交，只有显式给出起点时才携带 start_date。"""
    client, state = service
    state["responses"] = _catalog([_OWN]) + [(200, {"submit_recompute_count": 1})]
    assert client.products.recompute("own") == {"submit_recompute_count": 1}
    submit = state["requests"][-1]
    assert (submit[0], submit[1]) == ("POST", "/api/rqams/v2/products:recompute")
    assert json.loads(submit[2]) == {"product_ids": ["p1"]}
    state["responses"] = _catalog([_OWN]) + [(200, {"submit_recompute_count": 1})]
    client.products.recompute("own", start_date="2026-08-01")
    assert json.loads(state["requests"][-1][2]) == {"product_ids": ["p1"], "start_date": "2026-08-01"}


def test_compute_state_reads_state_without_waiting(service):
    """状态查询是无副作用的普通 GET，原样返回 state 与 execution_id，不轮询也不等待。"""
    client, state = service
    state["responses"] = _catalog([_OWN]) + [(200, {"state": "normal", "execution_id": 376})]
    assert client.products.compute_state("own") == {"state": "normal", "execution_id": 376}
    request = state["requests"][-1]
    assert (request[0], request[1]) == ("GET", "/api/rqams/v2/products/p1/compute_state")
    assert request[2] == b""
    # 目录四次 + 状态一次：状态不是任务句柄，不追加任何轮询请求。
    assert len(state["requests"]) == 5


def test_product_group_recompute_posts_group_ids_only(service):
    """产品组重算按组 ID 数组提交，产品选择器必须在写入前被类型检查拒绝。"""
    client, state = service
    group = {"id": "g1", "name": "grp", "user_id": 1}
    state["responses"] = _catalog([], groups=[group]) + [(200, {"submit_recompute_count": 1})]
    assert client.product_groups.recompute("grp") == {"submit_recompute_count": 1}
    request = state["requests"][-1]
    assert (request[0], request[1]) == ("POST", "/api/rqams/v2/product_groups:recompute")
    assert json.loads(request[2]) == {"product_group_ids": ["g1"]}
    state["responses"] = _catalog([_OWN])
    with pytest.raises(HarnessError) as error:
        client.product_groups.recompute("own")
    assert error.value.code == "unsupported_resource"


