"""Migration 0020: the shopkeeper sets the shop's name, prices and whether it prints in colour; an order with several
files, each with its own settings, reaches the shop computer with the order's file count and total."""
import copy

import pdfs
from sample_data import RULES
from test_agent_api import Agent
from test_shop_dashboard import H, err, key_for


def test_shopkeeper_reads_and_changes_name_and_prices(client, shop, api_db_url, raw_db):
    key = key_for(api_db_url, shop.code)
    assert client.get("/v1/shop/settings", headers=H("0" * 64)).status_code == 401
    now = client.get("/v1/shop/settings", headers=H(key)).json()
    assert now["shop_name"] == "Test Shop" and now["color_enabled"] is True and now["rate_card_version"] == 1
    assert now["bw"]["simplex"][0]["paise_per_side"] == 200

    rules = copy.deepcopy(RULES)
    rules["bw"]["simplex"] = [{"from_sides": 1, "to_sides": 20, "paise_per_side": 300},
                              {"from_sides": 21, "to_sides": None, "paise_per_side": 150}]
    r = client.post("/v1/shop/settings", headers=H(key), json={"shop_name": "  Sai Xerox  ", **rules})
    assert r.status_code == 200, r.text
    assert r.json()["shop_name"] == "Sai Xerox" and r.json()["rate_card_version"] == 2

    # customers see the new name and the new prices; the old price list is kept, retired
    assert client.get(f"/v1/shops/{shop.code}").json()["name"] == "Sai Xerox"
    assert client.get(f"/v1/shops/{shop.code}/rates").json()["bw"]["simplex"][1]["paise_per_side"] == 150
    assert raw_db.one("SELECT count(*) FROM ap.rate_cards WHERE shop_id = %s AND retired_at IS NOT NULL", (shop.id,)) == 1

    # saving the same prices again does not make another version
    same = client.post("/v1/shop/settings", headers=H(key), json=rules)
    assert same.json()["rate_card_version"] == 2


def test_bad_settings_change_nothing(client, shop, api_db_url):
    key = key_for(api_db_url, shop.code)
    gap = copy.deepcopy(RULES)
    gap["bw"]["simplex"] = [{"from_sides": 1, "to_sides": 20, "paise_per_side": 300},
                            {"from_sides": 30, "to_sides": None, "paise_per_side": 150}]
    assert err(client.post("/v1/shop/settings", headers=H(key), json=gap)) == "invalid_items"
    assert client.post("/v1/shop/settings", headers=H(key), json={"bw": RULES["bw"]}).status_code == 422   # half a price list
    assert client.post("/v1/shop/settings", headers=H(key), json={"shop_name": "   "}).status_code == 422
    assert client.post("/v1/shop/settings", headers=H(key), json={"shop_name": "x" * 81}).status_code == 422
    assert client.post("/v1/shop/settings", headers=H("0" * 64), json={"shop_name": "Mine now"}).status_code == 401
    now = client.get("/v1/shop/settings", headers=H(key)).json()
    assert now["shop_name"] == "Test Shop" and now["rate_card_version"] == 1


def test_a_shop_without_colour_tells_customers_and_refuses_a_colour_quote(client, shop, flow, api_db_url):
    key = key_for(api_db_url, shop.code)
    assert client.get(f"/v1/shops/{shop.code}").json()["color_available"] is True
    off = client.post("/v1/shop/settings", headers=H(key), json={"color_enabled": False})
    assert off.status_code == 200 and off.json()["color_enabled"] is False and off.json()["shop_name"] == "Test Shop"
    assert client.get(f"/v1/shops/{shop.code}").json()["color_available"] is False

    flow.create_order()
    doc = flow.upload(pdfs.blank(2))
    assert flow.finalize(doc).status_code == 200
    refused = flow.quote([{"document_id": doc, "options": {"color": True}}])
    assert refused.status_code == 409 and err(refused) == "color_not_available"
    assert flow.quote([{"document_id": doc, "options": {"color": False}}]).status_code == 201


def test_several_files_each_with_its_own_settings_reach_the_shop_as_one_order(client, shop, flow, raw_db):
    flow.create_order()
    a, b = flow.upload(pdfs.blank(3), "notes.pdf"), flow.upload(pdfs.blank(2), "poster.pdf")
    assert flow.finalize(a).status_code == 200 and flow.finalize(b).status_code == 200
    q = flow.quote([{"document_id": a, "options": {"copies": 2, "duplex": True}},
                    {"document_id": b, "options": {"color": True}}])
    assert q.status_code == 201, q.text
    assert [i["amount_paise"] for i in q.json()["items"]] == [3 * 2 * 120, 2 * 1000] and q.json()["total_paise"] == 2720
    assert len(flow.submit(q.json()["quote_id"]).json()["job_ids"]) == 2

    jobs = Agent(client, shop, raw_db).poll().json()["jobs"]
    # both jobs are made in one transaction, so their order in the list is not fixed
    assert sorted((j["document_name"], j["copies"], j["color"], j["duplex"]) for j in jobs) == [("notes.pdf", 2, False, True), ("poster.pdf", 1, True, False)]
    assert all(j["order_files"] == 2 and j["order_total_paise"] == 2720 for j in jobs)
    assert len({j["order_short_code"] for j in jobs}) == 1
