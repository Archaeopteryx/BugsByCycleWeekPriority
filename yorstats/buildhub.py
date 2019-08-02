# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import requests
import time
from logger import logger
import utils


URL = (
    'https://buildhub.prod.mozaws.net/v1/buckets/build-hub/collections/releases/search'
)


def make_request(params, sleep, retry, callback):
    """Query Buildhub"""
    params = json.dumps(params)

    for _ in range(retry):
        r = requests.post(URL, data=params)
        if 'Backoff' in r.headers:
            time.sleep(sleep)
        else:
            try:
                return callback(r.json())
            except BaseException as e:
                logger.error(
                    'Buildhub query failed with parameters: {}.'.format(params)
                )
                logger.error(e, exc_info=True)
                return None

    logger.error('Too many attempts in buildhub.make_request (retry={})'.format(retry))

    return None


def get_date(data):
    buckets = data['aggregations']['buildids']['buckets']
    if len(buckets) >= 1:
        buildid = buckets[0]['key']
        return utils.get_build_date(buildid)
    return utils.get_date('today')


def get_query(major, channels):
    version_pat = '{}[0-9\.]+(([ab][0-9]+))?'.format(major)
    return {
        'aggs': {
            'buildids': {
                'terms': {
                    'field': 'build.id',
                    'size': 1000,
                    'order': {'_term': 'asc'},
                }
            },
        },
        'query': {
            'bool': {
                'filter': [
                    {'regexp': {'target.version': {'value': version_pat}}},
                    {'terms': {'target.channel': channels}},
                    {'terms': {'source.product': ['firefox', 'fennec', 'devedition']}},
                ]
            }
        },
        'size': 0,
    }


def get_range(major):
    """Get the date of the first nightly and the first date of release"""
    data = get_query(major, ['nightly', 'aurora', 'beta'])
    first = make_request(data, 1, 100, get_date)
    data = get_query(major, ['release'])
    last = make_request(data, 1, 100, get_date)
    
    return first, last


def get_first_beta(major):
    """Get the date of the first beta"""
    data = get_query(major, ['aurora', 'beta'])
    first = make_request(data, 1, 100, get_date)
    
    return first
