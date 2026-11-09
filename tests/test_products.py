"""产品块的块内补齐：存在性检查路由、重算与状态查询、封账、异步转换与工作空间级检查。"""

import json

import pytest

from test_client import catalog_routes, service
from rqamsh.errors import HarnessError


def _catalog(products, units=None, groups=()):
    """登记目录路由：产品与产品组的逐项详情由列表项派生，资产单元原样给出。"""
    return catalog_routes(products=products, groups=groups, units=units or ())


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
    state["catalog"] = _catalog([_OWN])
    # 轮询复用提交路径（只多一个 task_id query），属于普通业务 GET，走业务队列。
    state["responses"] = [(202, {"task_id": "task-a"}), (200, {"status": "SUCCESS", "progress": 1, "data": None})]
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
    state["responses"] = [(200, rows)]
    # p2 的详情读不到（403），所以它不进目录，汇总结果里同样要被排除。
    state["catalog"] = catalog_routes(
        products=[{"id": "p1", "name": "own", "user_id": 1}, {"id": "p2", "name": "hidden", "user_id": 2}],
        denied=["p2"],
    )
    assert client.products.valuation_report_missing_dates() == [rows[0]]
    assert any(item[1] == "/api/rqams/v2/products:valuation_report_missing_date" for item in state["requests"])


def test_uploaded_file_hashes_resolves_ids_without_permission_lookup(service):
    """解析只读目录，不额外查询权限：他人产品照常解析，请求按解析后的 ID 提交。"""
    client, state = service
    # 同一客户端只登记一份目录（含他人产品）：写入会作废缓存，第二次解析由同一路由表重建。
    state["catalog"] = _catalog([_OWN, {"id": "p2", "name": "shared", "user_id": 2}])
    state["responses"] = [(200, [{"product_id": "p1", "hash_list": ["h1"]}])]
    assert client.products.uploaded_file_hashes(["own"], "trade") == [{"product_id": "p1", "hash_list": ["h1"]}]
    assert json.loads(state["requests"][-1][2]) == {"product_ids": ["p1"], "file_type": "trade"}
    state["requests"].clear()
    state["responses"] = [(200, [{"product_id": "p2", "hash_list": []}])]
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
    state["catalog"] = _catalog([_OWN])
    state["responses"] = [(200, b"")]
    assert client.products.set_closing_entry("own", "2026-08-31") is None
    request = state["requests"][-1]
    assert (request[0], request[1]) == ("PUT", "/api/rqams/v2/products/p1/closing_entry")
    assert json.loads(request[2]) == {"closing_date": "2026-08-31"}
    # 每次写入都作废目录缓存，第二次解析由同一路由表重建。
    state["responses"] = [(200, b"")]
    assert client.products.clear_closing_entry("own") is None
    assert (state["requests"][-1][0], state["requests"][-1][1]) == ("DELETE", "/api/rqams/v2/products/p1/closing_entry")


def test_recompute_submits_product_ids_and_optional_start_date(service):
    """重算按产品 ID 数组提交，只有显式给出起点时才携带 start_date。"""
    client, state = service
    state["catalog"] = _catalog([_OWN])
    state["responses"] = [(200, {"submit_recompute_count": 1})]
    assert client.products.recompute("own") == {"submit_recompute_count": 1}
    submit = state["requests"][-1]
    assert (submit[0], submit[1]) == ("POST", "/api/rqams/v2/products:recompute")
    assert json.loads(submit[2]) == {"product_ids": ["p1"]}
    state["responses"] = [(200, {"submit_recompute_count": 1})]
    client.products.recompute("own", start_date="2026-08-01")
    assert json.loads(state["requests"][-1][2]) == {"product_ids": ["p1"], "start_date": "2026-08-01"}


def test_compute_state_reads_state_without_waiting(service):
    """状态查询是无副作用的普通 GET，原样返回 state 与 execution_id，不轮询也不等待。"""
    client, state = service
    state["catalog"] = _catalog([_OWN])
    state["responses"] = [(200, {"state": "normal", "execution_id": 376})]
    assert client.products.compute_state("own") == {"state": "normal", "execution_id": 376}
    request = state["requests"][-1]
    assert (request[0], request[1]) == ("GET", "/api/rqams/v2/products/p1/compute_state")
    assert request[2] == b""
    # 目录四条（三个集合 + 一条详情）+ 状态一次：状态不是任务句柄，不追加任何轮询请求。
    assert len(state["requests"]) == 5


@pytest.mark.parametrize("accounts", [[], None])
def test_create_preserves_explicit_empty_or_null_accounts(service, accounts):
    """明确空账户与错误的 null 不被缺省账户静默覆盖。"""
    client, state = service
    state["responses"] = [(200, {"product_id": "p1"})]
    client.products.create({"name": "显式空账户", "accounts": accounts})
    assert json.loads(state["requests"][-1][2])["accounts"] == accounts


def test_create_preserves_account_overrides_without_mutating_nested_input(service):
    """补账户缺项时不篡改已提供的通道、账号、托管标记或调用方嵌套对象。"""
    client, state = service
    state["responses"] = [(200, {"product_id": "p1"})]
    payload = {"name": "显式账户", "data_source": "trade", "accounts": [
        {"account_number": "REAL-001", "broker": "citic", "is_custodian": True},
        {"name": "自选账户", "account_number": None, "broker": None},
    ]}
    original = json.loads(json.dumps(payload))
    client.products.create(payload)
    sent = json.loads(state["requests"][-1][2])
    assert sent["data_source"] == "trade"
    assert sent["accounts"][0]["account_number"] == "REAL-001"
    assert sent["accounts"][0]["broker"] == "citic"
    assert sent["accounts"][0]["is_custodian"] is True
    assert sent["accounts"][1]["name"] == "自选账户"
    assert sent["accounts"][1]["account_number"] is None
    assert sent["accounts"][1]["broker"] is None
    assert payload == original


def test_create_generated_account_names_avoid_explicit_names(service):
    """缺省账户名不能撞到显式账户，否则按名称选择会使用错误通道。"""
    client, state = service
    state["responses"] = [(200, {"product_id": "p1"})]
    client.products.create({"name": "产品", "accounts": [
        {"name": "产品交易账号2", "broker": "citic"}, {},
    ]})
    accounts = json.loads(state["requests"][-1][2])["accounts"]
    assert accounts[0]["name"] == "产品交易账号2"
    assert accounts[0]["name"] != accounts[1]["name"]


@pytest.mark.parametrize("name", ["产" * 47, "产" * 50])
def test_create_generated_account_name_respects_server_length_bound(service, name):
    """长产品名生成的缺省账户名仍在服务端五十字限制内。"""
    client, state = service
    state["responses"] = [(200, {"product_id": "p1"})]
    client.products.create({"name": name})
    account_name = json.loads(state["requests"][-1][2])["accounts"][0]["name"]
    assert len(account_name) <= 50
    assert account_name.endswith("交易账号")


def test_create_long_product_names_do_not_collapse_to_same_account_name(service):
    """同长前缀不同产品不能因截短共用账户名而触发空间唯一索引冲突。"""
    client, state = service
    state["responses"] = [(200, {"product_id": "p1"}), (200, {"product_id": "p2"})]
    names = []
    for ending in ("A", "B"):
        client.products.create({"name": "产" * 46 + ending})
        names.append(json.loads(state["requests"][-1][2])["accounts"][0]["name"])
    assert names[0] != names[1]
    assert all(len(name) <= 50 for name in names)


def test_create_keeps_explicit_unit_policy_without_mutating_input(service):
    """显式 manual 不被自动默认覆盖，调用方输入保持原样，份额策略交由服务端判定。"""
    client, state = service
    state["responses"] = [(200, {"product_id": "p1"})]
    payload = {
        "data_source": "trade", "name": "手工份额产品", "start_date": "2026-01-01",
        "unit_policy": "manual",
        "investment_category": "equity", "strategy_category": "stock_long",
        "benchmark": {"type": "index", "id": "000300.XSHG"}, "calendar": "exchange",
    }
    original = dict(payload)
    assert client.products.create(payload) == {"product_id": "p1"}
    sent = json.loads(state["requests"][-1][2])
    assert sent["unit_policy"] == "manual"
    assert sent["report_name"] == "手工份额产品"
    assert payload == original


def test_create_does_not_fill_unit_policy_for_valuation_report_source(service):
    """纯估值报告源不需要 unit_policy，客户端不能为创建成功越权补造该字段。"""
    client, state = service
    state["responses"] = [(200, {"product_id": "p1"})]
    payload = {
        "data_source": "valuation_report", "name": "估值源产品", "start_date": "2026-01-01",
        "investment_category": "equity", "strategy_category": "stock_long",
        "benchmark": {"type": "index", "id": "000300.XSHG"}, "calendar": "exchange",
    }
    original = dict(payload)
    assert client.products.create(payload) == {"product_id": "p1"}
    sent = json.loads(state["requests"][-1][2])
    assert "unit_policy" not in sent
    assert "accounts" not in sent
    assert sent["report_name"] == "估值源产品"
    assert payload == original


def test_create_surfaces_partial_failure_with_created_product_id(service):
    """创建返回 err_msgs 时仍以 partial_failure 报错并保留已创建 product_id，避免全量重复创建。"""
    client, state = service
    state["responses"] = [(200, {"product_id": "p1", "err_msgs": ["估值初始化失败"]})]
    payload = {
        "data_source": "trade", "name": "部分失败产品", "start_date": "2026-01-01",
        "investment_category": "equity", "strategy_category": "stock_long",
        "benchmark": {"type": "index", "id": "000300.XSHG"}, "calendar": "exchange",
    }
    with pytest.raises(HarnessError) as error:
        client.products.create(payload)
    assert error.value.code == "partial_failure"
    assert error.value.details["results"]["product_id"] == "p1"


def test_product_group_recompute_posts_group_ids_only(service):
    """产品组重算按组 ID 数组提交，产品选择器必须在写入前被类型检查拒绝。"""
    client, state = service
    group = {"id": "g1", "name": "grp", "user_id": 1}
    state["catalog"] = _catalog([], groups=[group])
    state["responses"] = [(200, {"submit_recompute_count": 1})]
    assert client.product_groups.recompute("grp") == {"submit_recompute_count": 1}
    request = state["requests"][-1]
    assert (request[0], request[1]) == ("POST", "/api/rqams/v2/product_groups:recompute")
    assert json.loads(request[2]) == {"product_group_ids": ["g1"]}
    # 换成只有自有产品的目录：产品选择器必须在写入前被类型检查拒绝，不发任何写入请求。
    state["catalog"] = _catalog([_OWN])
    with pytest.raises(HarnessError) as error:
        client.product_groups.recompute("own")
    assert error.value.code == "unsupported_resource"


