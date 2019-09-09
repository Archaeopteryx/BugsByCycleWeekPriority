# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This scripts generates a report of the number of bugs created by week and
# grouped by severity for a given version number which got fixed before the
# release of that version.
# It does not imply that the code regressed during that version number, only
# that it initially got reported when it was in either Nightly (central) or
# Beta stage. The issue can have affected also lower version numbers if it got
# missed before or the regressing code got added to repository containing the
# lower version number ("uplift").

import argparse
import csv
from dateutil.relativedelta import relativedelta
import json
from libmozdata.bugzilla import Bugzilla
from logger import logger
import buildhub, utils

# TODO: Drop deprecated severities once existing uses have been updated
#       https://bugzilla.mozilla.org/show_bug.cgi?id=1564608
SEVERITIES = {'blocker': 'blocker+critical+major',
              'critical': 'blocker+critical+major',
              'major': 'blocker+critical+major',
              'normal': 'normal',
              'minor': 'minor+trivial',
              'trivial': 'minor+trivial'}

WFMT = '{}-{:02d}'

# Bugzilla data can be loaded from file
bugzilla_data_loaded = None

# Bugzilla data can be saved froto file
bugzilla_data_to_save = {}


def add_bugzilla_data_to_save(node_path, data):
    # node_path is an array of strings representing the nodes in the JSON to
    # which the data shall be saved. The node has a child 'data' which holds the
    # data.
    node = bugzilla_data_to_save
    for path_step in node_path:
        if not path_step in node:
            node[path_step] = {'data': []}
        node = node[path_step]
    node['data'].append(data)


def get_weeks(start_date, end_date):
    res = []
    while start_date.strftime('%Y-%W') <= end_date.strftime('%Y-%W'):
        y, w, _ = start_date.isocalendar()
        res.append(WFMT.format(y, w))
        start_date += relativedelta(days=7)
    return res


def get_bugs(major):

    def bug_handler(bug, data):
        if bzdata_save_path:
            add_bugzilla_data_to_save(['opened', 'nightly'], bug)
        sev = bug['severity']
        creation = utils.get_date(bug['creation_time'])
        year, week, _ = creation.isocalendar()
        t = WFMT.format(year, week)
        data[SEVERITIES[sev]][t] += 1

    # start_date is the date for the first nightly
    # final_date is the date for the first release (or today if no release)
    start_date, final_date = buildhub.get_range(major)
    weeks = get_weeks(start_date, final_date)
    data = {sev: {w: 0 for w in weeks} for sev in set(SEVERITIES.values())}
    queries = []
    fields = ['creation_time', 'severity']
    params = {
        'include_fields': fields,
        'product': [
            'Core',
            'DevTools',
            'Firefox',
            'Firefox Build System',
            'Firefox for Android',
            'Testing',
            'Toolkit',
            'WebExtensions',
        ],
        'f1': 'creation_ts',
        'o1': 'greaterthaneq',
        'v1': '',
        'f2': 'creation_ts',
        'o2': 'lessthan',
        'v2': '',
        'f3': 'cf_last_resolved',
        'o3': 'lessthan',
        'v3': final_date,
        'f4': 'bug_severity',
        'o4': 'notequals',
        'v4': 'enhancement',
        'f5': 'keywords',
        'o5': 'notsubstring',
        'v5': 'meta',
        'f6': 'resolution',
        'o6': 'isnotempty',
        'f7': 'cf_status_firefox' + str(major),
        'o7': 'anyexact',
        'v7': 'affected, fix-optional, fixed, wontfix, verified, disabled'
    }

    # Load Bugzilla data from file
    if bzdata_load_path:
        for bug_data in bugzilla_data_loaded['opened']['nightly']['data']:
            bug_handler(bug_data, data)
    # Load Bugzilla data from Bugzilla server
    else:
        while start_date <= final_date:
            end_date = start_date + relativedelta(days=30)
            params = params.copy()

            # start_date <= creation_ts < end_date
            params['v1'] = start_date
            params['v2'] = end_date
            
            logger.info('Bugzilla: From {} To {}'.format(start_date, end_date))

            queries.append(Bugzilla(params,
                                    bughandler=bug_handler,
                                    bugdata=data,
                                    timeout=960))
            start_date = end_date

        for q in queries:
            q.get_data().wait()

    first_beta = buildhub.get_first_beta(major)
    y, w, _ = first_beta.isocalendar()
    data['first_beta'] = WFMT.format(y, w)

    return data


def log(message):
    print(message)


def write_csv(major):
    data = get_bugs(major)
    with open('data/bugs_count_{}.csv'.format(major), 'w') as Out:
        writer = csv.writer(Out, delimiter=',')
        weeks = list(sorted(data['normal'].keys()))
        head = ['Severity'] + weeks
        writer.writerow(head)
        for sev in ['blocker+critical+major', 'normal', 'minor+trivial']:
            numbers = data[sev]
            numbers = [numbers[w] for w in weeks]
            writer.writerow([sev] + numbers)
        writer.writerow([])
        writer.writerow(['First beta', data['first_beta']])


parser = argparse.ArgumentParser(description='Count bugs created and fixed before release, by week')
parser.add_argument('product_version', type=int,
                    help='Firefox version')
parser.add_argument('--bzdata-load',
                    nargs='?',
                    default=argparse.SUPPRESS,
                    help='Load the Bugzilla data from a local JSON file. If no path is provided '
                         'the program will try to load "bugzilla_data_<versionnumber>.json" from the "data" folder.')
parser.add_argument('--bzdata-save',
                    nargs='?',
                    default=argparse.SUPPRESS,
                    help='Save the Bugzilla data to a local JSON file. If no path is provided '
                         'the program will try to save as "bugzilla_data_<versionnumber>.json" into the "data" folder.')
args = parser.parse_args()

# Firefox version for which the report gets generated.
product_version = args.product_version

bzdata_load_path = None
if 'bzdata_load' in args:
    # Load Bugzilla data from file
    if args.bzdata_load:
        # File path provided as command line argument
        bzdata_load_path = args.bzdata_load
    else:
        # No file path provided, use default location
        bzdata_load_path = 'data/bugzilla_data_{}.json'.format(product_version)
    with open(bzdata_load_path, 'r') as bugzilla_data_reader:
        bugzilla_data_loaded = json.load(bugzilla_data_reader)
    log('Loaded Bugzilla data from {}'.format(bzdata_load_path))

bzdata_save_path = None
if 'bzdata_save' in args:
    # File path to which Bugzilla data shall be saved
    if args.bzdata_save:
        # File path provided as command line argument
        bzdata_save_path = args.bzdata_save
    else:
        # No file path provided, use default location
        bzdata_save_path = 'data/bugzilla_data_{}.json'.format(product_version)

write_csv(product_version)

if bzdata_save_path:
    # Save Bugzilla data to file
    with open('data/bugzilla_data_{}.json'.format(product_version), 'w') as bugzilla_data_writer:
        bugzilla_data_writer.write(json.dumps(bugzilla_data_to_save))
        log('Saved Bugzilla data to {}'.format(bzdata_save_path))

