# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This scripts generates a report of open security bugs rated with sec-critical
# or sec-high, containing
# * number of open bugs by week.
# * number of opened bugs by week.
# * number of closed bugs by week.
# * resolutions of bugs closed.
#
# The 'open' time
# * starts once 'sec-critical' or 'sec-high' gets added to the bugs' keywords
# * ends once
#   - the bug gets set as resolved
#   - neither 'sec-critical' or 'sec-high' is anymore in the keywords of the bug
#   - the keyword 'stalled' is added (either information to proceed missing like
#     data which can only captured during a violation and which is very rare, or
#     lack of developers to investigate further)
# If multiple affected time ranges are created by those, the time from the first
# time one of the security ratings got added to either the resolution of the bug
# or - if occurred before - the setting of the keyword 'stalled' or removal of
# the security rating from the keywords is regarded as the affected time.

import argparse
import copy
import csv
import datetime
from dateutil.relativedelta import relativedelta
import json
from libmozdata.bugzilla import Bugzilla
from logger import logger
import pytz
import utils

PRODUCTS_TO_CHECK = [
    'Core',
    'DevTools',
    'External Software Affecting Firefox',
    'Firefox',
    'Firefox Build System',
    'Firefox for Android',
    'Firefox for iOS',
    'GeckoView',
    'NSPR',
    'NSS',
    'Testing',
    'Toolkit',
    'WebExtensions',
]

critical = 'sec-critical'
high = 'sec-high'

SEC_RATINGS = [critical, high]

STATUS_GLOBAL_OPEN = ['UNCONFIRMED', 'NEW', 'ASSIGNED', 'REOPENED']
STATUS_GLOBAL_RESOLUTIONS = [
                             '---',
                             'FIXED',
                             'VERIFIED',
                             'INVALID',
                             'WONTFIX',
                             'INACTIVE',
                             'DUPLICATE',
                             'WORKSFORME',
                             'INCOMPLETE',
                             'SUPPORT',
                             'EXPIRED',
                             'MOVED',
                            ]

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
    weeks_attrs = {}
    while start_date.strftime('%Y-%W') <= end_date.strftime('%Y-%W'):
        y, w, _ = start_date.isocalendar()
        week_start, week_end = utils.get_week_bounds(start_date)
        week_label = WFMT.format(y, w)
        res.append(week_label)
        weeks_attrs[week_label] = {
                                  'week_start' : week_start,
                                  'week_end' : week_end,
                                 }
        start_date += relativedelta(days=7)
    return res, weeks_attrs


def get_bugs():

    def bug_handler(bug_data, other_data):
        if bzdata_save_path:
            add_bugzilla_data_to_save(['sec-critical-high'], bug_data)

        bug_creation_time_str = bug_data['creation_time']
        bug_creation_time = datetime.datetime.strptime(bug_creation_time_str, '%Y-%m-%dT%H:%M:%SZ')
        bug_creation_time = pytz.utc.localize(bug_creation_time)

        sec_important_start = None
        sec_important_end = None
        sec_important_rating = None

        sec_important_times = []
        stalled_added_last = None
        # Look for changes to the 'keywords' field.
        for historyItem in bug_data['history']:
            for change in historyItem['changes']:
                if change['field_name'] == 'keywords':
                    change_time_str = historyItem['when']
                    change_time = datetime.datetime.strptime(change_time_str, '%Y-%m-%dT%H:%M:%SZ')
                    change_time = pytz.utc.localize(change_time)

                    keywords_removed = change['removed'].split(', ')
                    keywords_added = change['added'].split(', ')

                    sec_rating_removed = critical in keywords_removed or high in keywords_removed
                    sec_rating_added = critical in keywords_added or high in keywords_added
                    if sec_rating_removed or sec_rating_added:
                        # Find and set security rating for time range.
                        if sec_rating_removed:
                            if critical in keywords_removed:
                                sec_important_rating = critical
                            elif high in keywords_removed:
                                sec_important_rating = high
                            if not sec_important_start:
                                sec_important_start = max(date_start, bug_creation_time)
                            sec_important_end = change_time
                            sec_important_times.append({
                                                        'rating' : sec_important_rating,
                                                        'start' : sec_important_start,
                                                        'end' : sec_important_end,
                                                      })
                        if sec_rating_added:
                            if critical in keywords_added:
                                sec_important_rating = critical
                            elif high in keywords_added:
                                sec_important_rating = high
                            sec_important_start = change_time
                        # no relevant security added
                        else:
                            sec_important_start = None
                            sec_important_rating = None
                        sec_important_end = None

                    # Bugs which got the 'stalled' keyword added are inactive
                    # and not counted as open (active).
                    stalled_removed = 'stalled' in keywords_removed
                    stalled_added = 'stalled' in keywords_added
                    if stalled_added:
                        stalled_added_last = change_time
                    elif stalled_removed:
                        stalled_added_last = None
        if sec_important_start:
            # Open time range at the end of the investigated time range.
            if not sec_important_end:
                sec_important_end = date_end
            sec_important_times.append({
                                        'rating' : sec_important_rating,
                                        'start' : sec_important_start,
                                        'end' : sec_important_end,
                                      })
        # No keyword changes at all, keyword should have been set when bug got
        # created.
        if len(sec_important_times) == 0:
            keywords = bug_data['keywords']
            sec_important_rating = None
            if critical in keywords:
                sec_important_rating = critical
            elif high in keywords:
                sec_important_rating = high
            else:
                sys.exit('Found neither sec-critical nor sec-high in keywords but expected one of them.')
            sec_important_times.append({
                                        'rating' : sec_important_rating,
                                        'start' : max(date_start, bug_creation_time),
                                        'end' : date_end,
                                      })

        sec_open_end = None
        if critical in bug_data['keywords'] or high in bug_data['keywords']:
            if bug_data['is_open']:
                if 'stalled' in bug_data['keywords']:
                    # Open but stalled bug with a security rating
                    if stalled_added_last:
                        sec_open_end = max(stalled_added_last, date_start)
                    else:
                        # Can only get here if bug got created with 'stalled'
                        # keyword, e.g. if bug got cloned.
                        sec_open_end = max(date_start, bug_creation_time)
                else:
                    sec_open_end = date_end
            else:
                # Bug closed, last time it got resolved used as ended of
                # affected time range.
                last_resolved_str = bug_data['cf_last_resolved']
                last_resolved = datetime.datetime.strptime(last_resolved_str, '%Y-%m-%dT%H:%M:%SZ')
                last_resolved = pytz.utc.localize(last_resolved)
                sec_open_end = min(sec_important_times[-1]['end'], last_resolved)
        else:
            sec_open_end = sec_important_times[0]['start']
        stalled = True if 'stalled' in bug_data['keywords'] else False
        bug_data_to_export = {
                              'id' : bug_data['id'],
                              'rating' : sec_important_times[-1]['rating'],
                              'start' : sec_important_times[0]['start'],
                              'end' : sec_open_end,
                              'stalled' : stalled,
                              'status' : bug_data['status'],
                              'resolution' : bug_data['resolution'],
                            }
        bug_sec_open_ranges.append(bug_data_to_export)

    # Load Bugzilla data from file
    if bzdata_load_path:
        for bug_data in bugzilla_data_loaded['sec-critical-high']['data']:
            other_data = {}
            bug_handler(bug_data, other_data)
    # Load Bugzilla data from Bugzilla server
    else:
        queries = []
        fields = [
                  'id',
                  'creation_time',
                  'status',
                  'is_open',
                  'resolution',
                  'cf_last_resolved',
                  'keywords',
                  'history',
                 ]

        params = {
            'include_fields': fields,
            'product': PRODUCTS_TO_CHECK,
            'j_top' : 'OR',
            # Either the keywords 'sec-critical' or 'sec-high' got removed
            # after the given date.
            'f1' : 'OP',
            'j1' : 'AND_G',
            'f2' : 'keywords',
            'o2' : 'changedfrom',
            'v2' : 'sec-critical',
            'f3' : 'keywords',
            'o3' : 'changedafter',
            'v3' : '',
            'f4' : 'CP',
            'f5' : 'OP',
            'j5' : 'AND_G',
            'f6' : 'keywords',
            'o6' : 'changedfrom',
            'v6' : 'sec-high',
            'f7' : 'keywords',
            'o7' : 'changedafter',
            'v7' : '',
            'f8' : 'CP',
            # Or the bug still has either the keyword 'sec-critical' or
            # 'sec-high' and
            'f9' : 'OP',
            'f10' : 'keywords',
            'o10' : 'anywords',
            'v10' : 'sec-critical, sec-high',
            'f11' : 'OP',
            'j11' : 'OR',
            # ... got resolved after the given date ...
            'f12' : 'cf_last_resolved',
            'o12' : 'changedafter',
            'v12' : '',
            # or hasn't been resolved yet.
            'f13' : 'bug_status',
            'o13' : 'anywords',
            'v13' : 'UNCONFIRMED, NEW, ASSIGNED, REOPENED',
            'f14' : 'CP',
            'f15' : 'CP',
        }

        params['v3'] = date_start_str
        params['v7'] = date_start_str
        params['v12'] = date_start_str

        query = Bugzilla(params,
                         bughandler=bug_handler,
                         bugdata={},
                         timeout=960)
        query.get_data().wait()


def log(message):
    print(message)


def aggregate_to_weekly_reports():
    for bug_sec_data in bug_sec_open_ranges:
        weeks_affected, unused_week_attrs = get_weeks(bug_sec_data['start'], bug_sec_data['end'])
        for week in weeks_affected:
            if week < weeks[0]:
                continue
            if week == weeks_affected[-1] and (bug_sec_data['status'] not in STATUS_GLOBAL_OPEN or bug_sec_data['stalled']):
                continue
            bug_sec_data_dict[bug_sec_data['rating']][week][bug_sec_data['id']] = bug_sec_data

    for sec_rating in bug_sec_data_dict:
        for week_pos in range(len(weeks) - 1, -1, -1):
            week = weeks[week_pos]
            open_by_week[sec_rating][week] = len(bug_sec_data_dict[sec_rating][week])

    for sec_rating in bug_sec_data_dict:
        for week_pos in range(len(weeks) - 1, 0, -1):
            week_this = weeks[week_pos]
            week_prev = weeks[week_pos - 1]
            open_this = set(bug_sec_data_dict[sec_rating][week_this].keys())
            open_prev = set(bug_sec_data_dict[sec_rating][week_prev].keys())
            opened_bugs = open_this - open_prev
            closed_bugs = open_prev - open_this
            opened_by_week[sec_rating][week_this] = len(opened_bugs)
            closed_by_week[sec_rating][week_this] = len(closed_bugs)
            for bug_id in closed_bugs:
                bug_data = bug_sec_data_dict[sec_rating][week_prev][bug_id]
                if bug_data['status'] not in STATUS_GLOBAL_OPEN:
                    resolution = bug_data['resolution']
                    if resolution not in STATUS_GLOBAL_RESOLUTIONS:
                        resolution = 'unknown'
                elif bug_data['stalled']:
                    resolution = 'stalled'
                resolutions_by_week[resolution][week_this] += 1


def write_csv():
    with open('data/security_bugs_report.csv', 'w') as Out:
        writer = csv.writer(Out, delimiter=',')

        date_row = ['Monday date']
        for week_pos in range(len(weeks) - 1, -1, -1):
            w = weeks[week_pos]
            date_row.append(weeks_attrs[w]['week_start'].strftime('%Y-%m-%d'))

        writer.writerow(['Open security bugs by week'])
        writer.writerow(date_row)

        for sec_rating in SEC_RATINGS:
            sec_rating_row = [sec_rating]
            for week_pos in range(len(weeks) - 1, -1, -1):
                w = weeks[week_pos]
                sec_rating_row.append(open_by_week[sec_rating][w])
            writer.writerow(sec_rating_row)
        sec_rating_total_row = ['Total']
        for week_pos in range(len(weeks) - 1, -1, -1):
            w = weeks[week_pos]
            sec_rating_total = 0
            for sec_rating in SEC_RATINGS:
                sec_rating_total += open_by_week[sec_rating][w]
            sec_rating_total_row.append(sec_rating_total)
        writer.writerow(sec_rating_total_row)

        writer.writerow([])
        writer.writerow([])

        writer.writerow(['Opened security bugs by week'])
        writer.writerow(date_row)

        for sec_rating in SEC_RATINGS:
            sec_rating_row = [sec_rating]
            for week_pos in range(len(weeks) - 1, 0, -1):
                w = weeks[week_pos]
                sec_rating_row.append(opened_by_week[sec_rating][w])
            writer.writerow(sec_rating_row)
        sec_rating_total_row = ['Total']
        for week_pos in range(len(weeks) - 1, 0, -1):
            w = weeks[week_pos]
            sec_rating_total = 0
            for sec_rating in SEC_RATINGS:
                sec_rating_total += opened_by_week[sec_rating][w]
            sec_rating_total_row.append(sec_rating_total)
        writer.writerow(sec_rating_total_row)

        writer.writerow([])
        writer.writerow([])

        writer.writerow(['Closed security bugs by week'])
        writer.writerow(date_row)

        for sec_rating in SEC_RATINGS:
            sec_rating_row = [sec_rating]
            for week_pos in range(len(weeks) - 1, 0, -1):
                w = weeks[week_pos]
                sec_rating_row.append(closed_by_week[sec_rating][w])
            writer.writerow(sec_rating_row)
        sec_rating_total_row = ['Total']
        for week_pos in range(len(weeks) - 1, 0, -1):
            w = weeks[week_pos]
            sec_rating_total = 0
            for sec_rating in SEC_RATINGS:
                sec_rating_total += closed_by_week[sec_rating][w]
            sec_rating_total_row.append(sec_rating_total)
        writer.writerow(sec_rating_total_row)

        writer.writerow([])
        writer.writerow([])

        writer.writerow(['Resolutions of security bugs by week'])
        writer.writerow(date_row)

        for resolution in STATUS_GLOBAL_RESOLUTIONS + ['stalled', 'unknown']:
            resolution_row = [resolution]
            for week_pos in range(len(weeks) - 1, 0, -1):
                w = weeks[week_pos]
                resolution_row.append(resolutions_by_week[resolution][w])
            writer.writerow(resolution_row)
        writer.writerow(sec_rating_total_row)

        writer.writerow([])
        writer.writerow(['"stalled" is not a Resolution status but a keyword which is added if either ' + \
                         'information to proceed is missing like data which can only captured during a ' + \
                         'violation and which is very rare, or lack of developers to investigate further.'])
        writer.writerow(['"unknown" is catching resolutions unknown to this script, should be new to ' + \
                         'bugzilla.mozilla.org'])


parser = argparse.ArgumentParser(description='Count security bugs opened and closed by week')
parser.add_argument('--bzdata-load',
                    nargs='?',
                    default=argparse.SUPPRESS,
                    help='Load the Bugzilla data from a local JSON file. If no path is provided '
                         'the program will try to load "sec_bugs_bugzilla_data.json" from the "data" folder.')
parser.add_argument('--bzdata-save',
                    nargs='?',
                    default=argparse.SUPPRESS,
                    help='Save the Bugzilla data to a local JSON file. If no path is provided '
                         'the program will try to save as "sec_bugs_bugzilla_data.json" into the "data" folder.')
args = parser.parse_args()

# Start of time range used by report. Hardcoded default of 1 year.
date_start = datetime.datetime.now() - datetime.timedelta(days = 365)
date_start = pytz.utc.localize(date_start)
date_start_str = date_start.strftime('%Y-%m-%dT%H:%M:%SZ')

# End of time range used by report.
date_end = datetime.datetime.utcnow()
date_end = pytz.utc.localize(date_end)
date_end_str = date_end.strftime('%Y-%m-%dT%H:%M:%SZ')

weeks, weeks_attrs = get_weeks(date_start, date_end)

bzdata_load_path = None
if 'bzdata_load' in args:
    # Load Bugzilla data from file
    if args.bzdata_load:
        # File path provided as command line argument
        bzdata_load_path = args.bzdata_load
    else:
        # No file path provided, use default location
        bzdata_load_path = 'data/sec_bugs_bugzilla_data.json'
    with open(bzdata_load_path, 'r') as bugzilla_data_reader:
        bugzilla_data_loaded = json.load(bugzilla_data_reader)
    log('Loaded Bugzilla data from {}'.format(bzdata_load_path))
    date_start_str = bugzilla_data_loaded['date_start']['data'][0]
    date_start = datetime.datetime.strptime(date_start_str, '%Y-%m-%dT%H:%M:%SZ')
    date_start = pytz.utc.localize(date_start)
    log('Date start from loaded Bugzilla data: {}'.format(date_start_str))
    date_end_str = bugzilla_data_loaded['date_end']['data'][0]
    date_end = datetime.datetime.strptime(date_end_str, '%Y-%m-%dT%H:%M:%SZ')
    date_end = pytz.utc.localize(date_end)
    log('Date end from loaded Bugzilla data: {}'.format(date_end_str))

bzdata_save_path = None
if 'bzdata_save' in args:
    # File path to which Bugzilla data shall be saved
    if args.bzdata_save:
        # File path provided as command line argument
        bzdata_save_path = args.bzdata_save
    else:
        # No file path provided, use default location
        bzdata_save_path = 'data/sec_bugs_bugzilla_data.json'

# Holds the time range in which a bug was considered open (see top of file) and
# had security rating.
bug_sec_open_ranges = []
get_bugs()

bug_sec_data_dict = { sec_rating : { week : {} for week in weeks } for sec_rating in SEC_RATINGS }
report_data = { sec_rating : { week : set() for week in weeks } for sec_rating in SEC_RATINGS }
open_by_week = { sec_rating : { week : 0 for week in weeks } for sec_rating in SEC_RATINGS }
opened_by_week = { sec_rating : { week : 0 for week in weeks } for sec_rating in SEC_RATINGS }
closed_by_week = { sec_rating : { week : 0 for week in weeks } for sec_rating in SEC_RATINGS }
resolutions_by_week = { resolution : { week : 0 for week in weeks } for resolution in STATUS_GLOBAL_RESOLUTIONS }
# 'stalled' is not a Resolution status but a keyword which is added if either
# information to proceed is missing like data which can only captured during a
# violation and which is very rare, or lack of developers to investigate
# further.
resolutions_by_week['stalled'] = { week : 0 for week in weeks }
# 'unknown' is catching resolutions unknown to this script, should be new to
# bugzilla.mozilla.org
resolutions_by_week['unknown'] = { week : 0 for week in weeks }
aggregate_to_weekly_reports()

write_csv()

if bzdata_save_path:
    # Save Bugzilla data to file
    with open('data/sec_bugs_bugzilla_data.json', 'w') as bugzilla_data_writer:
        add_bugzilla_data_to_save(['date_start'], date_start_str)
        add_bugzilla_data_to_save(['date_end'], date_end_str)
        bugzilla_data_writer.write(json.dumps(bugzilla_data_to_save))
        log('Saved Bugzilla data to {}'.format(bzdata_save_path))

