#!/usr/bin/env python
# Licensed to Cloudera, Inc. under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  Cloudera, Inc. licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
import re
import urlparse
from datetime import datetime

from django.utils.formats import localize_input
from django.utils.translation import ugettext as _
from jobsub.parameterization import find_variables


LOG = logging.getLogger(__name__)

JSON_FIELDS = ('parameters', 'job_properties', 'files', 'archives', 'prepares', 'params',
               'deletes', 'mkdirs', 'moves', 'chmods', 'touchzs')
BOOLEAN_FIELDS = ('propagate_configuration','capture_output')
NUMBER_FIELDS = ('sub_workflow',)
GMT_TIME_FORMAT = "%Y-%m-%dT%H:%MGMT%z"
UTC_TIME_FORMAT = "%Y-%m-%dT%H:%MZ"
FREQUENCY_REGEX = r'^\$\{coord:(?P<frequency_unit>\w+)\((?P<frequency_number>\d+)\)\}$'


def format_field_value(field, value):
  if field in JSON_FIELDS:
    if not isinstance(value, basestring):
      return json.dumps(value)
  if field in NUMBER_FIELDS:
    if not isinstance(value, int):
      return int(value)
  if field in BOOLEAN_FIELDS:
    return str(value).lower() == 'true'
  return value


def format_dict_field_values(dictionary):
  for key in dictionary:
    dictionary[key] = format_field_value(key, dictionary[key])
  return dictionary


def model_to_dict(model):
  from django.db import models
  dictionary = {}
  for field in model._meta.fields:
    try:
      attr = getattr(model, field.name, None)
      if isinstance(attr, models.Model):
        dictionary[field.name] = attr.id
      elif isinstance(attr, datetime):
        dictionary[field.name] = str(attr)
      else:
        dictionary[field.name] = attr
    except Exception, e:
      LOG.debug(_("Could not set field %(field)s: %(exception)s") % {'field': field.name, 'exception': str(e)})
  return dictionary


def sanitize_node_dict(node_dict):
  for field in ['node_ptr', 'workflow']:
    if field in node_dict:
      del node_dict[field]
  return node_dict


def workflow_to_dict(workflow):
  workflow_dict = model_to_dict(workflow)
  node_list = [node.get_full_node() for node in workflow.node_list]
  nodes = [model_to_dict(node) for node in node_list]

  for index, node in enumerate(node_list):
    nodes[index]['child_links'] = [model_to_dict(link) for link in node.get_all_children_links()]

  workflow_dict['nodes'] = nodes

  return workflow_dict


def smart_path(path, mapping):
  # Try to prepend home_dir and FS scheme if needed.
  # If path starts by a parameter try to get its value from the list of parameters submitted by the user or the coordinator.
  # This dynamic checking enable the use of <prepares> statements in a workflow scheduled manually of by a coordinator.
  # The logic is a bit complicated but Oozie is not consistent with data paths, prepare, coordinator paths and Fs action.

  if not path.startswith('$') and not path.startswith('/') and not urlparse.urlsplit(path).scheme:
    path = '/user/%(username)s/%(path)s' % {'username': '${wf:user()}', 'path': path}

  if path.startswith('$'):
    variables = find_variables(path)
    for var in variables:
      prefix = '${%s}' % var
      if path.startswith(prefix):
        if var in mapping:
          if not urlparse.urlsplit(mapping[var]).scheme and not mapping[var].startswith('$'):
            path = '%(nameNode)s%(path)s' % {'nameNode': '${nameNode}', 'path': path}
  else:
    if not urlparse.urlsplit(path).scheme:
      path = '%(nameNode)s%(path)s' % {'nameNode': '${nameNode}', 'path': path}

  return path


def utc_datetime_format(utc_time):
  return utc_time.strftime(UTC_TIME_FORMAT)


def oozie_to_django_datetime(dt_string):
  try:
    return localize_input(datetime.strptime(dt_string, UTC_TIME_FORMAT))
  except ValueError:
    pass

  try:
    return localize_input(datetime.strptime(dt_string, GMT_TIME_FORMAT))
  except ValueError:
    pass

  return None


def oozie_to_hue_frequency(frequency_string):
  # Get frequency number and units from frequency
  # frequency units and number are just different parts of the EL function.
  matches = re.match(FREQUENCY_REGEX, frequency_string)
  return matches.group('frequency_unit'), matches.group('frequency_number')