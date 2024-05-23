# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import csv
import os
from libmozdata.bugzilla import Bugzilla, BugzillaUser
# from logger import logger
import statistics
import urllib.request

from people import People

from BugsByCycleWeekPriority.scripts.utils.bugzilla import BUG_LIST_WEB_URL, get_component_to_team, get_needinfo_histories


# import importlib.util
# import sys
# bugbot_people_spec = importlib.util.spec_from_file_location("bugbot.people", "../../bugbot/bugbot/people.py")
# bugbot_people_module = importlib.util.module_from_spec(bugbot_people_spec)
# sys.modules["bugbot.people"] = bugbot_people_module
# bugbot_people_spec.loader.exec_module(bugbot_people_module)
# bugbot_people_module.People()

import http
import logging
logger = logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True

people_cls = People()

BUGZILLA_CONFIG_URL = 'https://bugzilla.mozilla.org/rest/configuration'

# PRODUCTS_TO_CHECK = [
#     'Core',
#     'DevTools',
#     'Firefox',
#     'Toolkit',
# ]

# TEAMS_IGNORED = [
#   'Credential Management',
#   'Desktop Integrations',
#   'Frontend',
#   'New Tab Page',
#   'Onboarding, Messaging, and Communication',
#   'Pocket and User Journey',
#   'Search and New Tab',
#   'Search Next Generation',
#   'Services',
#   'Telemetry',
#   'Web Extensions',
# ]

MANAGER_ROOT = 'aoverholt@mozilla.com'

# Bot accounts etc.
USERS_IGNORED = [
  'necko@mozilla.com',
]

def filter_data_by_employee_status(needinfos_open_by_user, employees):

    employees_mails = [employee['bugzillaEmail'] for employee in employees]
    needinfos_open_by_employee = {}
    for needinfoed_user in needinfos_open_by_user:
        if needinfoed_user in employees_mails:
            needinfos_open_by_employee[needinfoed_user] = needinfos_open_by_user[needinfoed_user]['needinfos']

    needinfos_open_by_component = {}
    for needinfoed_employee in needinfos_open_by_employee.keys():
        for bug_data in needinfos_open_by_employee[needinfoed_employee]:
            product_component = f'{bug_data["product"]} :: {bug_data["component"]}'
            if product_component not in needinfos_open_by_component:
                needinfos_open_by_component[product_component] = []
            needinfos_open_by_component[product_component].append(bug_data)

    needinfos_open_by_bugzilla_team = {}
    for needinfoed_employee in needinfos_open_by_employee.keys():
        for bug_data in needinfos_open_by_employee[needinfoed_employee]:
            team = bug_data['team']
            if team not in needinfos_open_by_bugzilla_team:
                needinfos_open_by_bugzilla_team[team] = []
            needinfos_open_by_bugzilla_team[team].append(bug_data)

    needinfos_open_by_bugzilla_team_and_employee = {}
    for needinfoed_employee in needinfos_open_by_employee.keys():
        for bug_data in needinfos_open_by_employee[needinfoed_employee]:
            team = bug_data['team']
            if team not in needinfos_open_by_bugzilla_team_and_employee:
                needinfos_open_by_bugzilla_team_and_employee[team] = {}
            if needinfoed_employee not in needinfos_open_by_bugzilla_team_and_employee[team]:
                needinfos_open_by_bugzilla_team_and_employee[team][needinfoed_employee] = []
            needinfos_open_by_bugzilla_team_and_employee[team][needinfoed_employee].append(bug_data)

    needinfos_open_by_manager = {}
    # only direct reports taken into account
    for needinfoed_employee in needinfos_open_by_employee.keys():
        for bug_data in needinfos_open_by_employee[needinfoed_employee]:
            manager = people_cls.get_info(needinfoed_employee)['manager']['dn']
            if manager not in needinfos_open_by_manager:
                needinfos_open_by_manager[manager] = []
            needinfos_open_by_manager[manager].append(bug_data)

    needinfos_open_by_manager_and_employee = {}
    for needinfoed_employee in needinfos_open_by_employee.keys():
        for bug_data in needinfos_open_by_employee[needinfoed_employee]:
            manager = people_cls.get_info(needinfoed_employee)['manager']['dn']
            if manager not in needinfos_open_by_manager_and_employee:
                needinfos_open_by_manager_and_employee[manager] = {}
            if needinfoed_employee not in needinfos_open_by_manager_and_employee[manager]:
                needinfos_open_by_manager_and_employee[manager][needinfoed_employee] = []
            needinfos_open_by_manager_and_employee[manager][needinfoed_employee].append(bug_data)


    return (
             needinfos_open_by_employee,
             needinfos_open_by_component,
             needinfos_open_by_bugzilla_team,
             needinfos_open_by_bugzilla_team_and_employee,
             needinfos_open_by_manager,
             needinfos_open_by_manager_and_employee,
           )


def get_bugs():

    def bug_handler(bug_data):
        bugs_data.append(bug_data)

    bugs_data = []

    fields = [
              'id',
             ]

    params = {
        'include_fields': fields,
        # 'product': PRODUCTS_TO_CHECK,
        'f1': 'flagtypes.name',
        'o1': 'substring',
        'v1': 'needinfo',
        # TODO: remove restriction, only added to keep dataset small for debugging
        # 'creation_ts': '2024-04-15',
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
                # if team in TEAMS_IGNORED:
                #     continue

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

def get_employees_with_needinfos(user_names):

    def user_handler(user_data):
        if user_data['email'] in USERS_IGNORED:
            return
        if not user_data['can_login']:
            return
        
        is_employee_bugbot = people_cls.is_mozilla(user_data['email'])
        is_employee_bugzilla = 'mozilla-employee-confidential' in [group['name'] for group in user_data['groups']]
        if is_employee_bugbot != is_employee_bugzilla:
            if 'softvision' in user_data['email']:
                print(user_data)
            employees_without_bzmail_set.append(user_data['email'])
        
        if is_employee_bugbot:
            employees.append(user_data['email'])
                
    def fault_user_handler(fault_data):
        # Definition of the function generates `permissive=True` parameter in
        # used library libmozdata which prevents failures if a user changed email
        # or deleted their account.
        pass

    employees = []
    employees_without_bzmail_set = []

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
                         include_fields=['can_login', 'email', 'groups'],
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

    for employee_without_bzmail_set in employees_without_bzmail_set:
        print(f"employee without Bugzilla email set: {employee_without_bzmail_set}")
    print(f"employees without Bugzilla email set: {len(employees_without_bzmail_set)}")
    print(f"employees total: {len(employees)}")
    return employees


def get_employees_relevant_with_needinfos(employees):
    employees_relevant = []
    for employee in employees:
        if people_cls.is_under(employee, MANAGER_ROOT) or employee == MANAGER_ROOT:
            employees_relevant.append(people_cls.get_info(employee))
    return employees_relevant


def write_csv(needinfos_open_by_employee, needinfos_open_by_component, needinfos_open_by_bugzilla_team, needinfos_open_by_bugzilla_team_and_employee, needinfos_open_by_manager, needinfos_open_by_manager_and_employee):
    directory_path = os.path.dirname(os.path.realpath(__file__))
    with open(f'{directory_path}/BugsByCycleWeekPriority/scripts/data/platform_org_needinfo_requests.csv', 'w') as Out:
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

        writer.writerow(['Open needinfo requests by Bugzilla team'])
        writer.writerow([])
        writer.writerow(['Team', 'Needinfo count', 'Bugs', 'Bugzilla link'])
        teams = sorted(needinfos_open_by_bugzilla_team.keys(), key=str.lower)
        for team in teams:
            writer.writerow([
                team,
                len(needinfos_open_by_bugzilla_team[team]),
                ','.join(sorted(list(set([str(bug_data['bug_id']) for bug_data in needinfos_open_by_bugzilla_team[team]])))),
                BUG_LIST_WEB_URL + ",".join(sorted(list(set([str(bug_data['bug_id']) for bug_data in needinfos_open_by_bugzilla_team[team]])))),
            ])

        writer.writerow([])
        writer.writerow([])

        writer.writerow(['Open needinfo requests by Bugzilla team and employee'])
        writer.writerow([])
        writer.writerow(['Team', 'Bugzilla email', 'Needinfo count', 'Bugs', 'Bugzilla link'])
        teams = sorted(needinfos_open_by_bugzilla_team_and_employee.keys(), key=str.lower)
        for team in teams:
            employees = sorted(needinfos_open_by_bugzilla_team_and_employee[team].keys(), key=str.lower)
            for employee in employees:
                writer.writerow([
                    team,
                    employee,
                    len(needinfos_open_by_bugzilla_team_and_employee[team][employee]),
                    ','.join(sorted(list(set([str(bug_data['bug_id']) for bug_data in needinfos_open_by_bugzilla_team_and_employee[team][employee]])))),
                    BUG_LIST_WEB_URL + ",".join(sorted(list(set([str(bug_data['bug_id']) for bug_data in needinfos_open_by_bugzilla_team_and_employee[team][employee]])))),
                ])

        writer.writerow([])
        writer.writerow([])

        writer.writerow(['Open needinfo requests by manager'])
        writer.writerow([])
        writer.writerow(['Manager', 'Needinfo count', 'Direct reports', 'Team average', 'Bugs', 'Bugzilla link'])
        managers = sorted(needinfos_open_by_manager.keys(), key=lambda manager: str.lower(people_cls.get_info(manager)['cn']))
        for manager in managers:
            manager_name = people_cls.get_info(manager)['cn']
            direct_reports = []
            employees_with_bzmail = people_cls.get_people_with_bzmail()
            for employee_with_bzmail in employees_with_bzmail:
                if people_cls.get_info(employee_with_bzmail)['manager']['dn'] == manager:
                    direct_reports.append(employee_with_bzmail)
            writer.writerow([
                manager_name,
                len(needinfos_open_by_manager[manager]),
                len(direct_reports),
                round(len(needinfos_open_by_manager[manager]) / len(direct_reports), 1), 
                ','.join(sorted(list(set([str(bug_data['bug_id']) for bug_data in needinfos_open_by_manager[manager]])))),
                BUG_LIST_WEB_URL + ",".join(sorted(list(set([str(bug_data['bug_id']) for bug_data in needinfos_open_by_manager[manager]])))),
            ])

        writer.writerow([])
        writer.writerow([])

        writer.writerow(['Open needinfo requests by manager and direct reports'])
        writer.writerow([])
        writer.writerow(['Manager', 'Direct report', 'Needinfo count', 'Bugs', 'Bugzilla link'])
        managers = sorted(needinfos_open_by_manager_and_employee.keys(), key=lambda manager: str.lower(people_cls.get_info(manager)['cn']))
        for manager in managers:
            employees = sorted(needinfos_open_by_manager_and_employee[manager].keys(), key=lambda employee: str.lower(people_cls.get_info(employee)['cn']))
            manager_name = people_cls.get_info(manager)['cn']
            for employee in employees:
                employee_name = people_cls.get_info(employee)['cn']
                writer.writerow([
                    manager_name,
                    employee_name,
                    len(needinfos_open_by_manager_and_employee[manager][employee]),
                    ','.join(sorted(list(set([str(bug_data['bug_id']) for bug_data in needinfos_open_by_manager_and_employee[manager][employee]])))),
                    BUG_LIST_WEB_URL + ",".join(sorted(list(set([str(bug_data['bug_id']) for bug_data in needinfos_open_by_manager_and_employee[manager][employee]])))),
                ])

        writer.writerow([])
        writer.writerow([])

        needinfos_open_count_per_employee_with_needinfos_open = [
            len(needinfos_open_by_manager_and_employee[manager][employee])
            for manager in needinfos_open_by_manager_and_employee
            for employee in needinfos_open_by_manager_and_employee[manager]
        ]
        employees_relevant_with_needinfos_count = len(needinfos_open_count_per_employee_with_needinfos_open)
        
        employees_relevant = []
        employees_with_bzmail = people_cls.get_people_with_bzmail()
        for employee_with_bzmail in employees_with_bzmail:
            if people_cls.is_under(employee_with_bzmail, MANAGER_ROOT) or employee == MANAGER_ROOT:
                employees_relevant.append(employee_with_bzmail)

        writer.writerow(['Only employees with bugzilla.mozilla.org account set at people.mozilla.org taken into account'])
        writer.writerow(['Employees relevant = Employees in Platform organization'])
        writer.writerow(['Employees relevant with open needinfo requests', employees_relevant_with_needinfos_count])
        writer.writerow(['Employees relevant total', len(employees_relevant)])
        needinfos_open_count = sum([len(needinfos_open_by_manager[manager]) for manager in needinfos_open_by_manager])
        writer.writerow(['Needinfo requests for employees relevant', needinfos_open_count])
        needinfos_open_average_only_employees_with_needinfos_open = needinfos_open_count / employees_relevant_with_needinfos_count
        writer.writerow(['Average needinfo requests per relevant employee with needinfos', round(needinfos_open_average_only_employees_with_needinfos_open, 1)])
        needinfo_count_median_only_employees_with_needinfos_open = statistics.median(needinfos_open_count_per_employee_with_needinfos_open)
        writer.writerow(['Median needinfo requests per relevant employee with needinfos', needinfo_count_median_only_employees_with_needinfos_open])

        needinfos_open_count_per_employee_relevant = needinfos_open_count_per_employee_with_needinfos_open + [0] * (len(employees_relevant) - employees_relevant_with_needinfos_count)
        needinfos_open_average = sum(needinfos_open_count_per_employee_relevant) / len(employees_relevant)
        writer.writerow(['Average needinfo requests per relevant employee', round(needinfos_open_average, 1)])
        needinfo_count_median = statistics.median(needinfos_open_count_per_employee_relevant)
        writer.writerow(['Median needinfo requests per relevant employee', needinfo_count_median])



bugs_data = get_bugs()
needinfos_open_by_user = get_needinfo_data(bugs_data)
employees_with_needinfos = get_employees_with_needinfos(needinfos_open_by_user.keys())
employees_relevant_with_needinfos = get_employees_relevant_with_needinfos(employees_with_needinfos)
needinfos_open_by_employee, needinfos_open_by_component, needinfos_open_by_bugzilla_team, needinfos_open_by_bugzilla_team_and_employee, needinfos_open_by_manager, needinfos_open_by_manager_and_employee = filter_data_by_employee_status(needinfos_open_by_user, employees_relevant_with_needinfos)
write_csv(
    needinfos_open_by_employee,
    needinfos_open_by_component,
    needinfos_open_by_bugzilla_team,
    needinfos_open_by_bugzilla_team_and_employee,
    needinfos_open_by_manager,
    needinfos_open_by_manager_and_employee,
)
