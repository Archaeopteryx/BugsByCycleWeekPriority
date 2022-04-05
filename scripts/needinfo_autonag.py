# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This scripts generates a report of bugs which
# * have the severity S1 or S2

import argparse
import csv
import datetime
import json
from libmozdata.bugzilla import Bugzilla
from logger import logger
import productdates
import pytz
import re
import urllib.request

import logging
logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True

BUGZILLA_DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

PRODUCTS_TO_CHECK = [
    'Core',
    'DevTools',
    'Firefox',
    'Firefox Build System',
    'Testing',
    'Toolkit',
    'WebExtensions',
]

NEEDINFO_CREATOR_BUGZILLA_EMAIL = 'release-mgmt-account-bot@mozilla.tld'

# Maximum time difference between needinfo getting set and Bugzilla comment. Used
# to identify what the needinfo request got set for. Value in seconds.
TIME_DIFF_MAX_NEEDINFO_COMMENT = 5

def get_needinfo_histories(bug_data, start_date, end_date, needinfo_comment_identifier, needinfo_creator):
    needinfo_histories = {}
    comments = bug_data['history']
    comment_position = 0
    for historyItem in bug_data['history']:
        for change in historyItem['changes']:
            field = change['field_name']
            if field != 'flagtypes.name':
                continue
            if not change['added'].startswith('needinfo?') and not change['removed'].startswith('needinfo?'):
                continue
            if change['added'].startswith('needinfo?'):
                if needinfo_creator is not None and historyItem['who'] != needinfo_creator:
                    continue
                match = re.search('(?<=needinfo\?\()[^)]*(?=\))', change['added'])
                if not match:
                    continue
                user_needinfoed = match.group(0)
                needinfo_start = parse_time(historyItem['when'], BUGZILLA_DATETIME_FORMAT)
                if needinfo_comment_identifier is None:
                    if user_needinfoed not in needinfo_histories.keys():
                        needinfo_histories[user_needinfoed] = []
                    if len(needinfo_histories[user_needinfoed]) == 0 or needinfo_histories[user_needinfoed][-1]['end']:
                        needinfo_histories[user_needinfoed].append({
                            'start': needinfo_start,
                            'end': None,
                        })
                else:
                    for comment in bug_data['comments']:
                        if needinfo_creator is not None and comment['creator'] != needinfo_creator:
                            continue
                        if needinfo_comment_identifier not in comment['text']:
                            continue
                        comment_time = parse_time(comment['creation_time'], BUGZILLA_DATETIME_FORMAT)
                        if abs((needinfo_start - comment_time).total_seconds()) > TIME_DIFF_MAX_NEEDINFO_COMMENT:
                            continue
                        if user_needinfoed not in needinfo_histories.keys():
                            needinfo_histories[user_needinfoed] = []
                        # Under rare circumstances, it's possible the same person
                        # gets needinfo twice (e.g. with the API)
                        if len(needinfo_histories[user_needinfoed]) == 0 or needinfo_histories[user_needinfoed][-1]['end']:
                            needinfo_histories[user_needinfoed].append({
                                'start': needinfo_start,
                                'end': None,
                            })
                        break
            if change['removed'].startswith('needinfo?'):
                match = re.search('(?<=needinfo\?\()[^)]*(?=\))', change['removed'])
                if not match:
                    continue
                user_needinfoed = match.group(0)
                needinfo_end = parse_time(historyItem['when'], BUGZILLA_DATETIME_FORMAT)
                if user_needinfoed not in needinfo_histories.keys():
                    # Creation of needinfo flag missing or not by desired user.
                    # Even when a bug gets created and the needinfo flag used
                    # during the creation, it will be recorded as change after
                    # the bug got created.
                    continue
                if needinfo_histories[user_needinfoed][-1]['end'] is not None:
                    # Creation of needinfo not by desired user.
                    continue
                needinfo_histories[user_needinfoed][-1]['end'] = needinfo_end

    for user_needinfoed in needinfo_histories.keys():
        for i in range(len(needinfo_histories[user_needinfoed]) - 1, -1, -1):
            needinfo_start_date = needinfo_histories[user_needinfoed][i]['start'].date()
            if not (start_date <= needinfo_start_date < end_date):
                needinfo_histories[user_needinfoed].pop(i)
    return needinfo_histories

def get_needinfo_data(label, start_date, end_date, needinfo_comment_identifier, needinfo_creator=NEEDINFO_CREATOR_BUGZILLA_EMAIL):

    def bug_handler(bug_data):
        needinfo_histories = get_needinfo_histories(bug_data, start_date, end_date, needinfo_comment_identifier, needinfo_creator)
        for user_needinfoed in needinfo_histories.keys():
            for needinfo_history in needinfo_histories[user_needinfoed]:
                bugs_data.append({
                  'id': bug_data['id'],
                  'user_needinfoed': user_needinfoed,
                  'needinfo_history': needinfo_history,
                })

    fields = [
              'id',
              'comments',
              'history',
             ]

    params = {
        'include_fields': fields,
        'product': PRODUCTS_TO_CHECK,
    }

    if needinfo_comment_identifier is not None:
        params['j_top'] = 'AND_G',
        params['o1'] = 'changedby',
        params['f1'] = 'longdesc',
        params['v1'] = needinfo_creator,
        params['o2'] = 'changedafter',
        params['f2'] = 'longdesc',
        params['v2'] = start_date
        params['o3'] = 'changedbefore',
        params['f3'] = 'longdesc',
        params['v3'] = end_date
        params['o4'] = 'substring',
        params['f4'] = 'longdesc',
        params['v4'] = needinfo_comment_identifier,

    elif needinfo_creator is None:
        params['o2'] = 'changedafter',
        params['f2'] = 'flagtypes.name',
        params['v2'] = start_date
        params['o3'] = 'changedbefore',
        params['f3'] = 'flagtypes.name',
        params['v3'] = end_date

    bugs_data = []

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()

    return bugs_data

def measure_data_for_interval(time_interval):

    start_date = time_interval['from']
    end_date = time_interval['to']
    label = time_interval['label']
    data = {}
    data['assignee_no_login'] = get_needinfo_data(label, start_date, end_date, 'The bug assignee didn\'t login in')
    data['leave_open_no_activity'] = get_needinfo_data(label, start_date, end_date, 'The leave-open keyword is there and there is no activity')
    data['needinfo_regression_author'] = get_needinfo_data(label, start_date, end_date, 'since you are the author of the regressor')
    data['regressed_by_bug_missing'] = get_needinfo_data(label, start_date, end_date, 'could you fill (if possible) the regressed_by field')
    data['low_severity_many_votes_and_cc'] = get_needinfo_data(label, start_date, end_date, 'The severity field for this bug is relatively low')
    data['low_severity_high_security_rating'] = get_needinfo_data(label, start_date, end_date, 'However, the bug is flagged with the')
    data['severity_missing'] = get_needinfo_data(label, start_date, end_date, 'The severity field is not set for this bug.')
    data['patch_reviewed_but_not_landed'] = get_needinfo_data(label, start_date, end_date, 'which didn\'t land and no activity in this bug for')
    data['uplift_necessary'] = get_needinfo_data(label, start_date, end_date, 'is this bug important enough to require an uplift?')
    data['meta_bug_without_dependencies'] = get_needinfo_data(label, start_date, end_date, 'The meta keyword is there, the bug doesn\'t depend on other bugs and there is no activity')
    data['everybodys_needinfos'] = get_needinfo_data(label, start_date, end_date, None, needinfo_creator=None)

    return data

def log(message):
    print(message)

def parse_time(string, format_string):
    change_time = datetime.datetime.strptime(string, format_string)
    return pytz.utc.localize(change_time)

def measure_data(time_intervals):
    data_by_time_intervals = []
    for time_interval in time_intervals:
        data_by_time_intervals.append({
            'label': time_interval['label'],
            'data': measure_data_for_interval(time_interval)
        })
    return data_by_time_intervals

def write_csv(data_by_time_intervals):
    with open('data/needinfo_requests.csv', 'w') as Out:
        writer = csv.writer(Out, delimiter=',')

        writer.writerow(['Needinfo requests by auto nag bot'])

        needinfo_types = [
            {'key': 'assignee_no_login', 'value': 'Assignee has not logged into Bugzilla for 7 months'},
            {'key': 'leave_open_no_activity', 'value': 'leave-open keyword set but no recent activity'},
            {'key': 'needinfo_regression_author', 'value': 'User is developer of regressor'},
            {'key': 'regressed_by_bug_missing', 'value': '\'Regression\' keyword set but \'Regressed By\' empty'},
            {'key': 'low_severity_many_votes_and_cc', 'value': 'Low severity but many votes and CCs'},
            {'key': 'low_severity_high_security_rating', 'value': 'Low severity but high security rating'},
            {'key': 'severity_missing', 'value': 'Severity missing'},
            {'key': 'patch_reviewed_but_not_landed', 'value': 'Patch reviewed but not landed'},
            {'key': 'uplift_necessary', 'value': 'Uplift necessary? - patch landed but not for all affected branches'},
            {'key': 'meta_bug_without_dependencies', 'value': 'The meta keyword is there, the bug doesn\'t depend on other bugs and there is no activity'},
            {'key': 'everybodys_needinfos', 'value': 'Needinfo requests by everybody'},
        ]

        for needinfo_type in needinfo_types:
            needinfo_key = needinfo_type['key']

            writer.writerow([])
            writer.writerow([needinfo_type['value']])

            writer.writerow([
                '',
            ]
            +
            list(reversed([data_by_time_interval['label'] for data_by_time_interval in data_by_time_intervals]))
            )

            row = ['Needinfo requests set']
            for pos in range(len(data_by_time_intervals) - 1, -1, -1):
                data_by_time_interval = data_by_time_intervals[pos]
                data = data_by_time_interval['data']
                row.append(len(data[needinfo_key]))
            writer.writerow(row)

            row = ['Answered 0..1 week']
            for pos in range(len(data_by_time_intervals) - 1, -1, -1):
                data_by_time_interval = data_by_time_intervals[pos]
                data = data_by_time_interval['data']
                bugs_data = []
                for bug_data in data[needinfo_key]:
                    if bug_data['needinfo_history']['end'] is not None:
                        if (bug_data['needinfo_history']['end'] - bug_data['needinfo_history']['start']) / datetime.timedelta(weeks = 1) <= 1:
                            bugs_data.append(bug_data)
                row.append(len(bugs_data))
            writer.writerow(row)

            row = ['Answered 1..2 weeks']
            for pos in range(len(data_by_time_intervals) - 1, -1, -1):
                data_by_time_interval = data_by_time_intervals[pos]
                data = data_by_time_interval['data']
                bugs_data = []
                for bug_data in data[needinfo_key]:
                    if bug_data['needinfo_history']['end'] is not None:
                        if 1 < (bug_data['needinfo_history']['end'] - bug_data['needinfo_history']['start']) / datetime.timedelta(weeks = 1) <= 2:
                            bugs_data.append(bug_data)
                row.append(len(bugs_data))
            writer.writerow(row)

            row = ['Answered >2 weeks']
            for pos in range(len(data_by_time_intervals) - 1, -1, -1):
                data_by_time_interval = data_by_time_intervals[pos]
                data = data_by_time_interval['data']
                bugs_data = []
                for bug_data in data[needinfo_key]:
                    if bug_data['needinfo_history']['end'] is not None:
                        if 2 < (bug_data['needinfo_history']['end'] - bug_data['needinfo_history']['start']) / datetime.timedelta(weeks = 1):
                            bugs_data.append(bug_data)
                row.append(len(bugs_data))
            writer.writerow(row)

            row = ['Unanswered']
            for pos in range(len(data_by_time_intervals) - 1, -1, -1):
                data_by_time_interval = data_by_time_intervals[pos]
                data = data_by_time_interval['data']
                bugs_data = []
                for bug_data in data[needinfo_key]:
                    if bug_data['needinfo_history']['end'] is None:
                        bugs_data.append(bug_data)
                row.append(len(bugs_data))
            writer.writerow(row)


parser = argparse.ArgumentParser(description='Count open, opened and closed Firefox bugs with severity S1 or S2 by developmen cycle or week')
parser.add_argument('--version-min', type=int,
                    help='Minimum Firefox version to check')
parser.add_argument('--weeks', type=int,
                    help='Number of recent weeks to check')
parser.add_argument('--debug',
                    action='store_true',
                    help='Show debug information')
args = parser.parse_args()
debug = args.debug

time_intervals = []
if args.weeks:
    for week_nr in range(args.weeks):
        now = datetime.datetime.utcnow()
        to_sunday = now.date() - datetime.timedelta(now.weekday() + 1 + 7 * week_nr)
        from_sunday = to_sunday - datetime.timedelta(7)
        time_intervals.append({
            'from': from_sunday,
            'to': to_sunday,
            'label': to_sunday.isoformat(),
        })
    time_intervals.reverse()
elif args.version_min:
    releases = productdates.get_latest_nightly_versions_by_min_version(args.version_min)
    for release_pos in range(len(releases)):
        if release_pos == len(releases) - 1:
            end_date = datetime.date.today() + datetime.timedelta(days = 1)
        else:
            end_date = releases[release_pos + 1]['date']
        version = releases[release_pos]['version']
        time_intervals.append({
            'from': releases[release_pos]['date'],
            'to': end_date,
            'label': str(releases[release_pos]['version']),
        })
else:
    import sys
    sys.exit('No time intervals requested')
data_by_time_intervals = measure_data(time_intervals)
write_csv(data_by_time_intervals)

