"""标签块：调用方私有的组织信息，读取无参数、写入与删除都用裸数组体。"""

import json

import pytest

from test_client import service
from rqamsh.errors import HarnessError


def test_tags_list_uses_product_tags_route_without_arguments(service):
    """读取标签不带参数，直接返回服务端数组；标签与绑定已由服务端按身份过滤。"""
    client, state = service
    state["responses"] = [(200, [{"tag_id": "t1", "name": "重点"}])]
    assert client.tags.list() == [{"tag_id": "t1", "name": "重点"}]
    assert (state["requests"][-1][0], state["requests"][-1][1].split("?")[0].endswith("/product_tags")) == ("GET", True)


def test_tags_upsert_sends_bare_array_and_reports_partial_failure(service):
    """写入体是标签数组本身；存在失败项时必须整体报错并保留逐项诊断，且不重复提交成功项。"""
    client, state = service
    payload = [{"name": "重点", "product_ids": ["p1"]}]
    state["responses"] = [(200, {"effect_count": 1, "detail": [{"tag_id": "t1", "success": True}]})]
    assert client.tags.upsert(payload) == {"effect_count": 1, "detail": [{"tag_id": "t1", "success": True}]}
    assert json.loads(state["requests"][-1][2]) == payload

    state["responses"] = [(200, {
        "effect_count": 1,
        "detail": [{"tag_id": "t1", "success": True}, {"tag_id": None, "success": False, "error_msg": "标签名重复"}],
    })]
    with pytest.raises(HarnessError) as error:
        client.tags.upsert([{"name": "重点"}, {"name": "重点"}])
    assert error.value.code == "partial_failure"
    assert error.value.details["failed"] == [{"tag_id": None, "success": False, "error_msg": "标签名重复"}]
    assert [request[0] for request in state["requests"]].count("POST") == 2


def test_tags_delete_sends_bare_id_array(service):
    """删除体是标签 ID 裸数组，不接受对象包装。"""
    client, state = service
    state["responses"] = [(200, {"effect_count": 1})]
    assert client.tags.delete(["t1"]) == {"effect_count": 1}
    assert json.loads(state["requests"][-1][2]) == ["t1"]


def test_tags_operations_reject_empty_batches(service):
    """空批次既无意义也会浪费服务端计算，必须本地拒绝且不发请求。"""
    client, state = service
    for method in ("upsert", "delete"):
        with pytest.raises(HarnessError) as error:
            getattr(client.tags, method)([])
        assert error.value.code == "invalid_argument"
    assert state["requests"] == []
