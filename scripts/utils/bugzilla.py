# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This scripts generates a report of bugs which
# * have the severity S1 or S2

import argparse
import datetime
import json
from libmozdata.bugzilla import Bugzilla
import pytz
import urllib.request

BUG_LIST_WEB_URL = 'https://bugzilla.mozilla.org/buglist.cgi?bug_id_type=anyexact&query_format=advanced&bug_id='
BUGZILLA_CONFIG_URL = 'https://bugzilla.mozilla.org/rest/configuration'

COMPONENT_TO_TEAM_MAP = None

STATUS_OPEN = ['UNCONFIRMED', 'NEW', 'ASSIGNED', 'REOPENED']
STATUS_UNAFFECTED = ['unaffected']
STATUS_UNKNOWN = ['---']

def get_component_to_team(product, component):
    global COMPONENT_TO_TEAM_MAP
    if COMPONENT_TO_TEAM_MAP is None:
        with urllib.request.urlopen(BUGZILLA_CONFIG_URL) as request_handle:
            data = json.loads(request_handle.read())

            ID_TO_PRODUCT = {}
            products_data = data['field']['product']['values']
            for pos in range(len(products_data)):
                if products_data[pos]['isactive'] == 0:
                    continue

                product_name = products_data[pos]['name']

                ID_TO_PRODUCT[products_data[pos]['id']] = product_name

            COMPONENT_TO_TEAM_MAP = {}
            components_data = data['field']['component']['values']
            for component_data in components_data:
                if component_data['isactive'] == 0:
                    continue

                if component_data['product_id'] not in ID_TO_PRODUCT.keys():
                    continue

                product_name = ID_TO_PRODUCT[component_data['product_id']]
                COMPONENT_TO_TEAM_MAP[f"{product_name} :: {component_data['name']}"] = component_data['team_name']
    product_component_requested = f"{product} :: {component}"
    if product_component_requested in COMPONENT_TO_TEAM_MAP:
        return COMPONENT_TO_TEAM_MAP[product_component_requested]
    return None

def get_relevant_bug_changes(bug_data, fields, start_date, end_date):
    bug_states = {}
    for field in fields:
        bug_states[field] = {
            "old": None,
            "new": None,
        }
    for historyItem in bug_data['history']:
        for change in historyItem['changes']:
            field = change['field_name']
            if field in fields:
                change_time_str = historyItem['when']
                change_time = datetime.datetime.strptime(change_time_str, '%Y-%m-%dT%H:%M:%SZ')
                change_time = pytz.utc.localize(change_time).date()
                if change_time < start_date:
                    bug_states[field]["old"] = change['added']
                elif start_date <= change_time < end_date:
                    if bug_states[field]["old"] is None:
                        bug_states[field]["old"] = change['removed']
                    bug_states[field]["new"] = change['added']
                if change_time > end_date:
                    if bug_states[field]["old"] is None:
                        bug_states[field]["old"] = change['removed']
                    if bug_states[field]["new"] is None:
                        bug_states[field]["new"] = change['removed']
    for field in fields:
        if bug_states[field]["old"] is None:
            bug_states[field]["old"] = bug_data[field]
        if bug_states[field]["new"] is None:
            bug_states[field]["new"] = bug_data[field]
    return bug_states


