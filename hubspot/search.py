import logging
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

import requests
from babel.numbers import get_currency_symbol

logger = logging.getLogger(__name__)

HS_GCLID_PROPERTY = "hs_google_click_id"


# --------------------------------------------------------
# Search contact by gclid
# --------------------------------------------------------

def search_contact_by_gclid(gclid, access_token, property_name=HS_GCLID_PROPERTY):
    url = "https://api.hubapi.com/crm/v3/objects/contacts/search"
    headers = {"Authorization": f"Bearer {access_token}"}

    def do_search(prop):
        payload = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": prop,
                            "operator": "EQ",
                            "value": gclid
                        }
                    ]
                }
            ],
            "limit": 1
        }
        return requests.post(url, headers=headers, json=payload, timeout=10)

    res = do_search(property_name)

    if res.status_code == 400:
        logger.warning(
            "HubSpot rejected property '%s'. Retrying with '%s'.",
            property_name,
            HS_GCLID_PROPERTY
        )
        res = do_search(HS_GCLID_PROPERTY)

    if res.status_code != 200:
        logger.error("HubSpot contact search failed: %s", res.text)
        return None

    data = res.json()

    if not data.get("results"):
        return None

    return data["results"][0]


# --------------------------------------------------------
# Get contact with correct HubSpot properties
# --------------------------------------------------------

def get_contact(contact_id, access_token):
    url = f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}"
    headers = {"Authorization": f"Bearer {access_token}"}

    params = {
        # Pull both "meetings booked" and "meetings logged" counters so we can
        # support whichever property the HubSpot portal actively uses.
        "properties": "email,lifecyclestage,hs_meetings_booked,hs_meetings_logged,num_associated_meetings"
    }

    return requests.get(url, headers=headers, params=params).json()


# --------------------------------------------------------
# Get contact's company
# --------------------------------------------------------

def get_contact_company(contact_id, access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}/associations/companies"

    r = requests.get(url, headers=headers).json()

    if not r.get("results"):
        return None

    company_id = r["results"][0]["id"]

    url2 = f"https://api.hubapi.com/crm/v3/objects/companies/{company_id}"
    params = {
        # Grab name plus aggregate deal metrics so the caller does not need to
        # search through each deal to find these numbers.
        "properties": "name,hs_total_deal_value,hs_total_open_amount,hs_num_open_deals"
    }

    return requests.get(url2, headers=headers, params=params).json()


# --------------------------------------------------------
# Meetings associated with a contact
# --------------------------------------------------------

def get_contact_meetings(contact_id, access_token, min_date=None):
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}/associations/meetings"

    response = requests.get(url, headers=headers).json()
    if "results" not in response:
        return []

    meetings = []
    for result in response["results"]:
        meeting_id = result.get("id")
        if not meeting_id:
            continue

        detail_url = f"https://api.hubapi.com/crm/v3/objects/meetings/{meeting_id}"
        params = {
            "properties": "hs_meeting_title,hs_meeting_body,hs_meeting_start_time,"
                          "hs_meeting_end_time,hs_meeting_outcome,hs_meeting_notes,hs_meeting_location,"
                          "hs_createdate,createdate"
        }
        meeting_data = requests.get(detail_url, headers=headers, params=params).json()
        props = meeting_data.get("properties", {})

        if min_date:
            meeting_date = parse_hubspot_datetime(props.get("hs_meeting_start_time"))
            if meeting_date and meeting_date < min_date:
                continue

        meetings.append({
            "id": meeting_data.get("id"),
            "title": props.get("hs_meeting_title"),
            "notes": props.get("hs_meeting_body") or props.get("hs_meeting_notes"),
            "start_time": props.get("hs_meeting_start_time"),
            "end_time": props.get("hs_meeting_end_time"),
            "outcome": props.get("hs_meeting_outcome"),
            "location": props.get("hs_meeting_location"),
            "createdate": props.get("hs_createdate") or props.get("createdate"),
        })

    return meetings


# --------------------------------------------------------
# Get all deals associated with the company
# --------------------------------------------------------

def parse_hubspot_datetime(value):
    if not value:
        return None

    try:
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=dt_timezone.utc)

        if isinstance(value, str) and value.isdigit():
            timestamp = float(value)
            if len(value) > 10:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=dt_timezone.utc)

        if isinstance(value, str):
            normalized = value.replace("Z", "+00:00")
            dt_obj = datetime.fromisoformat(normalized)
            if dt_obj.tzinfo is None:
                dt_obj = dt_obj.replace(tzinfo=dt_timezone.utc)
            return dt_obj
    except ValueError:
        return None

    return None


def parse_amount(value):
    if value is None:
        return None

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def is_open_deal(props):
    val = props.get("hs_is_closed")
    if isinstance(val, str):
        return val.lower() not in ("true", "1")
    if isinstance(val, (bool, int)):
        return not bool(val)
    return True


def get_company_deals(company_id, access_token, min_date=None):
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api.hubapi.com/crm/v3/objects/companies/{company_id}/associations/deals"

    r = requests.get(url, headers=headers).json()

    if "results" not in r:
        return []

    deals = []
    for d in r["results"]:
        deal_id = d["id"]
        url2 = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}"
        params = {
            "properties": "dealname,dealstage,amount,hs_total_open_amount,hs_num_open_deals,hs_currency,"
                          "closedate,hs_createdate,createdate,hs_is_closed"
        }
        deal_data = requests.get(url2, headers=headers, params=params).json()

        if min_date:
            props = deal_data.get("properties", {})
            deal_date = (
                parse_hubspot_datetime(props.get("closedate"))
                or parse_hubspot_datetime(props.get("hs_createdate"))
                or parse_hubspot_datetime(props.get("createdate"))
            )

            if not deal_date or deal_date < min_date:
                continue

        if not is_open_deal(deal_data.get("properties", {})):
            continue

        deals.append(deal_data)

    return deals


# --------------------------------------------------------
# Get default HubSpot account currency (fallback)
# --------------------------------------------------------

def get_account_currency(access_token):
    url = "https://api.hubapi.com/account-info/v3/details"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("companyCurrency")


# --------------------------------------------------------
# Format final output JSON
# --------------------------------------------------------

def format_response(contact, company, deals, meetings, currency_fallback):
    contact_props = contact.get("properties", {}) if contact else {}
    deal = deals[0] if deals else None
    deal_props = deal.get("properties", {}) if deal else {}
    company_props = company.get("properties", {}) if company else {}

    currency = deal_props.get("hs_currency") or currency_fallback

    if meetings:
        meetings_count = len(meetings)
    else:
        meetings_count = (
            contact_props.get("hs_meetings_booked")
            or contact_props.get("hs_meetings_logged")
            or contact_props.get("num_associated_meetings")
            or 0
        )

    serialized_deals = []
    total_amount = Decimal("0")
    has_amount = False
    for item in deals:
        props = item.get("properties", {})
        amount_value = (
            parse_amount(props.get("amount"))
            or parse_amount(props.get("hs_total_open_amount"))
        )
        if amount_value is not None:
            total_amount += amount_value
            has_amount = True

        serialized_deals.append({
            "id": item.get("id"),
            "dealname": props.get("dealname"),
            "dealstage": props.get("dealstage"),
            "amount": props.get("amount"),
            "hs_currency": props.get("hs_currency"),
            "closedate": props.get("closedate"),
            "hs_createdate": props.get("hs_createdate") or props.get("createdate"),
            "hs_is_closed": props.get("hs_is_closed"),
        })

    if not has_amount:
        total_amount = None

    deal_amount_number = len(serialized_deals)
    deal_amount = str(total_amount) if total_amount is not None else None
    deal_amount_value = float(total_amount) if total_amount is not None else None

    flat = {
        "email": contact_props.get("email"),
        "meeting_booked_number": meetings_count,
        "deal_amount_number": deal_amount_number,
        #"deal_amount": deal_amount,
        "deal_amount": deal_amount_value,
        "lifecyclestage": contact_props.get("lifecyclestage"),
        "companyname": company_props.get("name"),
        "currency": currency,
        "currency_symbol": get_currency_symbol(currency) if currency else None,
        #"deals": serialized_deals,
        #"meetings": meetings,
    }

    return flat
