from unittest.mock import patch

from opskit.api_client import InventoryClient, summarize_hosts


def test_list_hosts_follows_pagination():
    pages = {1: {"page": 1, "pages": 2, "items": [{"name": "a"}]},
             2: {"page": 2, "pages": 2, "items": [{"name": "b"}]}}
    client = InventoryClient("http://example.invalid", "t")
    with patch.object(client, "_get", side_effect=lambda path, page: pages[page]) as fake:
        hosts = client.list_hosts()
    assert [h["name"] for h in hosts] == ["a", "b"]
    assert fake.call_count == 2


def test_retry_policy_configured():
    client = InventoryClient("http://example.invalid", "t", retries=4)
    retry = client.session.get_adapter("http://example.invalid").max_retries
    assert retry.total == 4
    assert 503 in retry.status_forcelist
    assert "POST" not in retry.allowed_methods


def test_summarize_hosts():
    hosts = [{"name": "a", "role": "web", "env": "prod", "maintenance": True},
             {"name": "b", "role": "db", "env": "prod", "maintenance": False}]
    summary = summarize_hosts(hosts)
    assert summary["total"] == 2
    assert summary["by_env"] == {"prod": 2}
    assert summary["in_maintenance"] == ["a"]
