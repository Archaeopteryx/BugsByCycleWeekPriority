# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This scripts generates a report of bugs which
# * are defects
# * have the severity S1 or S2
# * either explicitly started with the given version (indicated by the status field for the version)
# * or got reported when the version was the current release and the version status field is not set to 'unaffected'.

import argparse
import csv
import datetime
from libmozdata.bugzilla import Bugzilla
from logger import logger
import productdates

PRODUCTS_TO_CHECK = [
    'Core',
    'DevTools',
    'Firefox',
    'Firefox Build System',
    'Testing',
    'Toolkit',
    'WebExtensions',
]

STATUS_OPEN = ['UNCONFIRMED', 'NEW', 'ASSIGNED', 'REOPENED']
STATUS_UNAFFECTED = ['unaffected']
STATUS_UNKNOWN = ['---']

def get_bugs(version, start_date, end_date):

    def bug_handler(bug_data):
        release_status = []
        for key, value in bug_data.items():
            if key.startswith('cf_status_firefox') and not key.startswith('cf_status_firefox_esr'):
                release_status.append({ key: value })
        release_status.sort(key = lambda item: list(item.keys())[0])

        version_first_affected = None
        for release_state in release_status:
            release_state_key, release_state_value = list(release_state.items())[0]
            if release_state_value in STATUS_UNAFFECTED or release_state_value in STATUS_UNKNOWN:
                continue
            else:
                version_first_affected = int((release_state_key.split('cf_status_firefox'))[1])
                break
        if version_first_affected is None:
            version_first_affected = version
        elif version_first_affected != version:
            if debug:
                log('First affected version for bug ' + str(bug_data['id']) + ' is ' + str(version_first_affected) + ', not ' + str(version) + ' we are interested in.')
            return
        bugs_data.append({
          'id': bug_data['id'],
          'severity': bug_data['severity'],
          'release_status': release_status,
        })
        return

    fields = [
              'id',
              'severity',
              '_custom',
             ]

    params = {
        'include_fields': fields,
        'bug_type': 'defect',
        'product': PRODUCTS_TO_CHECK,
        'severity': ['S1', 'S2'],
        'status': STATUS_OPEN,
        'f1': 'keywords',
        'o1': 'notsubstring',
        'v1': 'meta',
        # Ignore bugs created by the bot which creates one bug per
        # web-platform-test to sync.
        'f2': 'reporter',
        'o2': 'notequals',
        'v2': 'wptsync@mozilla.bugs',
        # Exclude intermittent failures which have priority P5 (= not
        # crashes). Imports of tests or issues affecting tests randomly
        # can increase the count of new intermittent bugs.
        'f3': 'OP',
        'n3': '1',
        'f4': 'keywords',
        'o4': 'allwords',
        'v4': 'intermittent-failure',
        'f5': 'priority',
        'o5': 'equals',
        'v5': 'P5',
        'f6': 'CP',
        # End of exclusion of intermittent failures.
        'f13': 'OP',
        'f14': 'cf_status_firefox' + str(version),
        'o14': 'anywords',
        'v14': ['affected', 'wontfix', 'fix-optional'],
        'f15': 'cf_status_firefox' + str(version - 1),
        'o15': 'nowords',
        'v15': ['affected', 'wontfix', 'fix-optional'],
        'f16': 'CP',
    }

    bugs_data = []

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()
    severity_buckets = {
      'S1_affected_set': [bug_data['id'] for bug_data in bugs_data if bug_data['severity'] == 'S1'],
      'S2_affected_set': [bug_data['id'] for bug_data in bugs_data if bug_data['severity'] == 'S2'],
    }

    params = {
        'include_fields': fields,
        'bug_type': 'defect',
        'product': PRODUCTS_TO_CHECK,
        'severity': ['S1', 'S2'],
        'status': STATUS_OPEN,
        'f1': 'keywords',
        'o1': 'notsubstring',
        'v1': 'meta',
        # Ignore bugs created by the bot which creates one bug per
        # web-platform-test to sync.
        'f2': 'reporter',
        'o2': 'notequals',
        'v2': 'wptsync@mozilla.bugs',
        # Exclude intermittent failures which have priority P5 (= not
        # crashes). Imports of tests or issues affecting tests randomly
        # can increase the count of new intermittent bugs.
        'f3': 'OP',
        'n3': '1',
        'f4': 'keywords',
        'o4': 'allwords',
        'v4': 'intermittent-failure',
        'f5': 'priority',
        'o5': 'equals',
        'v5': 'P5',
        'f6': 'CP',
        # End of exclusion of intermittent failures.
        'f9': 'creation_ts',
        'o9': 'greaterthan',
        'v9': '',
        'f10': 'creation_ts',
        'o10': 'lessthan',
        'v10': '',
        'f11': 'cf_status_firefox' + str(version),
        'o11': 'nowords',
        'v11': STATUS_UNAFFECTED,
        'f13': 'OP',
        'n13': '1',
        'f15': 'cf_status_firefox' + str(version),
        'o15': 'anywords',
        'v15': ['affected', 'wontfix', 'fix-optional'],
        'f16': 'cf_status_firefox' + str(version - 1),
        'o16': 'nowords',
        'v16': ['affected', 'wontfix', 'fix-optional'],
        'f18': 'CP',
    }

    params['v9'] = start_date
    params['v10'] = end_date

    bugs_data = []

    Bugzilla(params,
             bughandler=bug_handler,
             timeout=960).get_data().wait()
    severity_buckets['S1_affected_unknown'] = [bug_data['id'] for bug_data in bugs_data if bug_data['severity'] == 'S1']
    severity_buckets['S2_affected_unknown'] = [bug_data['id'] for bug_data in bugs_data if bug_data['severity'] == 'S2']

    return severity_buckets

def log(message):
    print(message)

def measure_data(releases):
    defect_data_by_version = []
    for release_pos in range(len(releases)):
        if release_pos == len(releases) - 1:
            end_date = datetime.date.today() + datetime.timedelta(days = 1)
        else:
            end_date = releases[release_pos + 1]['date']
        version = int((releases[release_pos]['version'].split('.'))[0])
        defect_data_by_version.append({
            'version': version,
            'defect_data': get_bugs(version,
                                    releases[release_pos]['date'],
                                    end_date)
        })
    return defect_data_by_version

def write_csv(defect_data_by_version):
    with open('data/open_defects.csv', 'w') as Out:
        writer = csv.writer(Out, delimiter=',')

        writer.writerow([
            'First affected version',
            'Open severity S1 bugs w/ affected set (count)',
            'Open severity S2 bugs w/ affected set (count)',
            'Open severity S1 bugs w/o affected set (count)',
            'Open severity S2 bugs w/o affected set (count)',
            'Open severity S1 bugs w/ affected set (bug numbers)',
            'Open severity S2 bugs w/ affected set (bug numbers)',
            'Open severity S1 bugs w/o affected set (bug numbers)',
            'Open severity S2 bugs w/o affected set (bug numbers)',
        ])

        for pos in range(len(defect_data_by_version) - 1, -1, -1):
            data_for_version = defect_data_by_version[pos]
            defect_data = data_for_version['defect_data']
            writer.writerow([
                data_for_version['version'],
                len(defect_data['S1_affected_set']),
                len(defect_data['S2_affected_set']),
                len(defect_data['S1_affected_unknown']),
                len(defect_data['S2_affected_unknown']),
                ','.join(sorted([str(bug_id) for bug_id in defect_data['S1_affected_set']])),
                ','.join(sorted([str(bug_id) for bug_id in defect_data['S2_affected_set']])),
                ','.join(sorted([str(bug_id) for bug_id in defect_data['S1_affected_unknown']])),
                ','.join(sorted([str(bug_id) for bug_id in defect_data['S2_affected_unknown']])),
            ])


parser = argparse.ArgumentParser(description='Count open defects with severity S1 or S2 by regressing version')
parser.add_argument('version_min', type=int,
                    help='Minimum Firefox version to check for open defects')
parser.add_argument('--debug',
                    action='store_true',
                    help='Show debug information')
args = parser.parse_args()
debug = args.debug

releases = productdates.get_latest_released_versions_by_min_version(args.version_min)
defect_data_by_version = measure_data(releases)
write_csv(defect_data_by_version)

