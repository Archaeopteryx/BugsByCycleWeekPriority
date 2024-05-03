# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import csv
from libmozdata.bugzilla import Bugzilla, BugzillaUser
from logger import logger
import urllib.request

from utils.bugzilla import BUG_LIST_WEB_URL, get_component_to_team, get_needinfo_histories

import http
import logging
logger = logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True

BUGZILLA_CONFIG_URL = 'https://bugzilla.mozilla.org/rest/configuration'

PRODUCTS_TO_CHECK = [
    'Core',
    'DevTools',
    'Firefox',
    'Toolkit',
]

TEAMS_IGNORED = [
  'Credential Management',
  'Desktop Integrations',
  'Frontend',
  'New Tab Page',
  'Onboarding, Messaging, and Communication',
  'Pocket and User Journey',
  'Search and New Tab',
  'Search Next Generation',
  'Services',
  'Telemetry',
  'Web Extensions',
]

def filter_data_by_employee_status(needinfos_open_by_user, employees):

    needinfos_open_by_employee = {}
    for needinfoed_user in needinfos_open_by_user:
        if needinfoed_user in employees:
            needinfos_open_by_employee[needinfoed_user] = needinfos_open_by_user[needinfoed_user]['needinfos']

    needinfos_open_by_component = {}
    for needinfoed_employee in needinfos_open_by_employee.keys():
        for bug_data in needinfos_open_by_employee[needinfoed_employee]:
            product_component = f'{bug_data["product"]} :: {bug_data["component"]}'
            if product_component not in needinfos_open_by_component:
                needinfos_open_by_component[product_component] = []
            needinfos_open_by_component[product_component].append(bug_data)

    needinfos_open_by_team = {}
    for needinfoed_employee in needinfos_open_by_employee.keys():
        for bug_data in needinfos_open_by_employee[needinfoed_employee]:
            team = bug_data['team']
            if team not in needinfos_open_by_team:
                needinfos_open_by_team[team] = []
            needinfos_open_by_team[team].append(bug_data)

    needinfos_open_by_team_and_employee = {}
    for needinfoed_employee in needinfos_open_by_employee.keys():
        for bug_data in needinfos_open_by_employee[needinfoed_employee]:
            team = bug_data['team']
            if team not in needinfos_open_by_team_and_employee:
                needinfos_open_by_team_and_employee[team] = {}
            if needinfoed_employee not in needinfos_open_by_team_and_employee[team]:
                needinfos_open_by_team_and_employee[team][needinfoed_employee] = []
            needinfos_open_by_team_and_employee[team][needinfoed_employee].append(bug_data)

    return needinfos_open_by_employee, needinfos_open_by_component, needinfos_open_by_team, needinfos_open_by_team_and_employee


def get_bugs():

    def bug_handler(bug_data):
        bugs_data.append(bug_data)

    bugs_data = []

    fields = [
              'id',
             ]

    params = {
        'include_fields': fields,
        'product': PRODUCTS_TO_CHECK,
        'f1': 'flagtypes.name',
        'o1': 'substring',
        'v1': 'needinfo',
    }

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    return bugs_data


def get_needinfo_data(bugs_data):

    def bug_handler(bug_data):
        needinfo_histories = get_needinfo_histories(bug_data)
        for needinfoed_user in needinfo_histories:
            for needinfo in needinfo_histories[needinfoed_user]:
                if needinfo['requester'] == needinfo['requestee']:
                    continue

                # TODO: adjust for answered needinfo requests for past measuring points
                if needinfo['end'] is not None:
                    continue

                product = bug_data['product']
                component = bug_data['component']
                team = get_component_to_team(product, component)
                if team in TEAMS_IGNORED:
                    continue

                if needinfoed_user not in needinfos_open_by_user:
                    needinfos_open_by_user[needinfoed_user] = {
                        'bug_ids': [],
                        'needinfos': [],
                    }
                bug_id = bug_data['id']
                if bug_id not in needinfos_open_by_user[needinfoed_user]['bug_ids']:
                    needinfos_open_by_user[needinfoed_user]['bug_ids'].append(bug_id)
                    needinfos_open_by_user[needinfoed_user]['needinfos'].append({
                        'bug_id': bug_id,
                        'user': needinfoed_user,
                        'team': team,
                        'product': product,
                        'component': component,
                    })

    needinfos_open_by_user = {}

    bucket_width = 500
    for bug_ids_start in range(0, len(bugs_data), bucket_width):
        fields = [
                  'id',
                  'creation_time',
                  'product',
                  'component',
                  'history',
                 ]

        params = {
            'include_fields': fields,
            'id': [bug['id'] for bug in bugs_data[bug_ids_start:min(bug_ids_start + bucket_width, len(bugs_data)) + 1]],
        }

        Bugzilla(params,
                 bughandler=bug_handler,
                 timeout=960).get_data().wait()

    return needinfos_open_by_user

def get_employees(user_names):

    def user_handler(user_data):
        if not user_data['can_login']:
            return
        groups = [group['name'] for group in user_data['groups']]
        if 'mozilla-employee-confidential' in groups:
            print(f"email: {user_data['email']} ldap email: {user_data['ldap_email'] if 'ldap_email' in user_data else None}")
            employees.append(user_data['email'])
                
    def fault_user_handler(fault_data):
        # Definition of the function generates `permissive=True` parameter in
        # used library libmozdata which prevents failures if a user changed email
        # or deleted their account.
        pass

    employees = []

    QUERY_STRING_LIMIT = 4000
    users_to_search = []
    user_search_string = ''
    for user_name in user_names:
        new_search_string_part = ''
        if user_search_string != '':
            new_search_string_part += '&'
        new_search_string_part += "names=" + user_name
        if len(user_search_string + new_search_string_part) > QUERY_STRING_LIMIT:
            BugzillaUser(user_names=users_to_search,
                         include_fields=['can_login', 'email', 'groups', 'ldap_email'],
                         user_handler=user_handler,
                         fault_user_handler=fault_user_handler,
                         timeout=960).wait()
            user_search_string = ''
            users_to_search = []
        user_search_string += new_search_string_part
        users_to_search.append(user_name)
    if users_to_search:
        BugzillaUser(user_names=users_to_search,
                     include_fields=['can_login', 'email', 'groups'],
                     user_handler=user_handler,
                     fault_user_handler=fault_user_handler,
                     timeout=960).wait()

    return employees

def write_csv(needinfos_open_by_employee, needinfos_open_by_component, needinfos_open_by_team, needinfos_open_by_team_and_employee):
    with open('data/platform_org_needinfo_requests.csv', 'w') as Out:
        writer = csv.writer(Out, delimiter=',')

        writer.writerow(['Open needinfo requests by employee'])
        writer.writerow([])
        writer.writerow(['Bugzilla email', 'Needinfo count', 'Bugs', 'Bugzilla link'])
        needinfoed_employees = sorted(needinfos_open_by_employee.keys(), key=str.lower)
        for needinfoed_employee in needinfoed_employees:
            writer.writerow([
                needinfoed_employee,
                len(needinfos_open_by_employee[needinfoed_employee]),
                ','.join(sorted([str(bug_data['bug_id']) for bug_data in needinfos_open_by_employee[needinfoed_employee]])),
                BUG_LIST_WEB_URL + ",".join(sorted([str(bug_data['bug_id']) for bug_data in needinfos_open_by_employee[needinfoed_employee]])),
            ])

        writer.writerow([])
        writer.writerow([])

        writer.writerow(['Open needinfo requests by component'])
        writer.writerow([])
        writer.writerow(['Product', 'Component', 'Needinfo count', 'Bugs', 'Bugzilla link'])
        product_components = sorted(needinfos_open_by_component.keys(), key=str.lower)
        for product_component in product_components:
            product, component = product_component.split(' :: ', 1)
            writer.writerow([
                product,
                component,
                len(needinfos_open_by_component[product_component]),
                ','.join(sorted(list(set([str(bug_data['bug_id']) for bug_data in needinfos_open_by_component[product_component]])))),
                BUG_LIST_WEB_URL + ",".join(sorted(list(set([str(bug_data['bug_id']) for bug_data in needinfos_open_by_component[product_component]])))),
            ])

        writer.writerow([])
        writer.writerow([])

        writer.writerow(['Open needinfo requests by team'])
        writer.writerow([])
        writer.writerow(['Team', 'Needinfo count', 'Bugs', 'Bugzilla link'])
        teams = sorted(needinfos_open_by_team.keys(), key=str.lower)
        for team in teams:
            writer.writerow([
                team,
                len(needinfos_open_by_team[team]),
                ','.join(sorted(list(set([str(bug_data['bug_id']) for bug_data in needinfos_open_by_team[team]])))),
                BUG_LIST_WEB_URL + ",".join(sorted(list(set([str(bug_data['bug_id']) for bug_data in needinfos_open_by_team[team]])))),
            ])

        writer.writerow([])
        writer.writerow([])

        writer.writerow(['Open needinfo requests by team and employee'])
        writer.writerow([])
        writer.writerow(['Team', 'Bugzilla email', 'Needinfo count', 'Bugs', 'Bugzilla link'])
        teams = sorted(needinfos_open_by_team_and_employee.keys(), key=str.lower)
        for team in teams:
            employees = sorted(needinfos_open_by_team_and_employee[team].keys(), key=str.lower)
            for employee in employees:
                writer.writerow([
                    team,
                    employee,
                    len(needinfos_open_by_team_and_employee[team][employee]),
                    ','.join(sorted(list(set([str(bug_data['bug_id']) for bug_data in needinfos_open_by_team_and_employee[team][employee]])))),
                    BUG_LIST_WEB_URL + ",".join(sorted(list(set([str(bug_data['bug_id']) for bug_data in needinfos_open_by_team_and_employee[team][employee]])))),
                ])

bugs_data = get_bugs()
needinfos_open_by_user = get_needinfo_data(bugs_data)
employees = get_employees(needinfos_open_by_user.keys())
needinfos_open_by_employee, needinfos_open_by_component, needinfos_open_by_team, needinfos_open_by_team_and_employee = filter_data_by_employee_status(needinfos_open_by_user, employees)
write_csv(needinfos_open_by_employee, needinfos_open_by_component, needinfos_open_by_team, needinfos_open_by_team_and_employee)
