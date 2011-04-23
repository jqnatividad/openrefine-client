#!/usr/bin/env python
"""
Client library to communicate with a Refine server.
"""

import csv
import json
import gzip
import os
import re
import StringIO
import urllib
import urllib2_file
import urllib2
import urlparse


REFINE_HOST = os.environ.get('GOOGLE_REFINE_HOST', '127.0.0.1')
REFINE_PORT = os.environ.get('GOOGLE_REFINE_PORT', '3333')


class Facet(object):
    def __init__(self, column, expression='value', omit_blank=False, omit_error=False, select_blank=False, select_error=False, invert=False):
        self.column = column
        self.name = column  # XXX not sure what the difference is yet
        self.expression = expression
        self.invert = invert
        self.omit_blank = omit_blank
        self.omit_error = omit_error
        self.select_blank = select_blank
        self.select_error = select_error

    def as_dict(self):
        return {
            'type': 'list',
            'name': self.column,
            'columnName': self.column,
            'expression': self.expression,
            'selection': [],    # XXX what is this?
            'omitBlank': self.omit_blank,
            'omitError': self.omit_error,
            'selectBlank': self.select_blank,
            'selectError': self.select_error,
            'invert': self.invert,
        }

class FacetResponse(object):
    def __init__(self, facet):
        self.name = facet['name']
        self.column = self.name
        self.expression = facet['expression']
        self.invert = facet['invert']
        self.choices = {}
        class FacetChoice(object):
            def __init__(self, c):
                self.count = c['c']
                self.selected = c['s']

        for choice in facet['choices']:
            self.choices[choice['v']['v']] = FacetChoice(choice)
        self.blank_choice = FacetChoice(facet['blankChoice'])


class FacetsResponse(object):
    def __init__(self, facets):
        self.facets = [FacetResponse(f) for f in facets['facets']]
        self.mode = facets['mode']


class Engine(object):
    def __init__(self, facets=None, mode='row-based'):
        if facets is None:
            facets = []
        elif not isinstance(facets, list):
            facets = [facets]
        self.facets = facets
        self.mode = mode
        
    def as_dict(self):
        return {
            'facets': [f.as_dict() for f in self.facets],   # XXX how with json?
            'mode': self.mode,
        }

    def as_json(self):
        return json.dumps(self.as_dict())

    def add_facet(self, facet):
        self.facets.append(facet)

class RefineServer(object):
    """Communicate with a Refine server."""

    def __init__(self, server='http://%s:%s' % (REFINE_HOST, REFINE_PORT)):
        self.server = server[:-1] if server.endswith('/') else server

    def urlopen(self, command, data=None, project_id=None):
        """Open a Refine URL and optionally POST data."""
        url = self.server + '/command/core/' + command
        if data is None:
            data = {}
        if project_id:
            if 'delete' in command:
                data['project'] = project_id
            else:
                url += '?project=' + project_id                
        req = urllib2.Request(url)
        if data:
            req.add_data(data) # data = urllib.urlencode(data)
        #req.add_header('Accept-Encoding', 'gzip')
        response = urllib2.urlopen(req)
        if response.info().get('Content-Encoding', None) == 'gzip':
            # Need a seekable filestream for gzip
            gzip_fp = gzip.GzipFile(fileobj=StringIO.StringIO(response.read()))
            # XXX Monkey patch response's filehandle. Better way?
            urllib.addbase.__init__(response, gzip_fp)
        return response
    
    def urlopen_json(self, *args, **kwargs):
        """Open a Refine URL, optionally POST data, and return parsed JSON."""
        response = self.urlopen(*args, **kwargs)
        data = response.read()
        response_json = json.loads(data)
        if 'code' in response_json and response_json['code'] == 'error':
            raise Exception(response_json['message'])
        return response_json


class Refine:
    """Class representing a connection to a Refine server."""
    def __init__(self, server, **kwargs):
        if isinstance(server, RefineServer):
            self.server = server
        else:
            self.server = RefineServer(server)

    def list_projects(self):
        """Return a dict of projects indexed by id & name.
        
        {u'1877818633188': {
            'id': u'1877818633188', u'name': u'akg',
            u'modified': u'2011-04-07T12:30:07Z',
            u'created': u'2011-04-07T12:30:07Z'
        },
        {u'akg': { ... } } ...}"""
        projects = self.server.urlopen_json('get-all-project-metadata')['projects']
        # Provide a way for projects to be indexed by name too
        for project_id, metadata in projects.items():
            metadata['id'] = project_id
            projects[metadata['name']] = metadata
        return projects

    def get_project_id_name(self, project):
        """Returns (project_id, project_name) given either."""
        projects = self.list_projects()
        # Is the project param an integer? If so treat as an id, else a name.
        if re.match(r'^\d+$', project):
            return project, projects[project]['name']
        else:
            return projects[project]['id'], project

    def open_project(self, project):
        """Open a Refine project referred to by id or name."""
        project_id, project_name = self.get_project_id_name(project)
        return RefineProject(self.server, project_id, project_name)

    def new_project(self, project_file=None, project_url=None, project_name=None,
        split_into_columns=True,
        separator='',
        ignore_initial_non_blank_lines=0,
        header_lines=1, # use 0 if your data has no header
        skip_initial_data_rows=0,
        limit=None, # no more than this number of rows
        guess_value_type=True,  # numbers, dates, etc.
        ignore_quotes=False):
        # Content-Disposition: form-data; name="project-file"; filename="duplicates.csv"
        # Accept-Encoding:gzip,deflate,sdch
        # POST http://0.0.0.0:3333/command/core/create-project-from-upload?
        # url=&split-into-columns=true&separator=&ignore=0&header-lines=1&skip=0&
        # limit=&guess-value-type=true&ignore-quotes=false
        # 302 Location:http://0.0.0.0:3333/project?project=2104489985696
        if (project_file and project_url) or (not project_file and not project_url):
            raise ValueError('One (only) of project_file and project_url must be set')
        def s(opt):
            if isinstance(opt, bool):
                return 'on' if opt else ''
            if opt is None:
                return ''
            return str(opt)
        options = {
            'split-into-columns': s(split_into_columns), 'separator': s(separator),
            'ignore': s(ignore_initial_non_blank_lines), 'header-lines': s(header_lines),
            'skip': s(skip_initial_data_rows), 'limit': s(limit),
            'guess-value-type': s(guess_value_type), 
            'ignore-quotes': s(ignore_quotes),
        }
        if project_url is not None:
            options['url'] = project_url
        elif project_file is not None:
            options['project-file'] = {
                'fd': open(project_file),
                'filename': project_file,
            }
        if project_name is None:
            # strip extension and directories
            project_name = (project_file or 'New project').rsplit('.', 1)[0]
            project_name = os.path.basename(project_name)
        options['project-name'] = project_name
        response = self.server.urlopen('create-project-from-upload', options)
        # expecting a redirect to the new project containing the id in the url
        url_params = urlparse.parse_qs(urlparse.urlparse(response.geturl()).query)
        if 'project' in url_params:
            project_id = url_params['project'][0]
            return RefineProject(self.server, project_id, project_name)
        else:
            raise Exception('Project not created')


class RefineProject:
    """A Google Refine project."""
    def __init__(self, server, project_id=None, project_name=None):
        if not isinstance(server, RefineServer):
            url = urlparse.urlparse(server)
            if url.query:
                # Parse out the project ID and create a base server URL
                project_id = url.query[8:]  # skip project=
                server = urlparse.urlunparse((url.scheme, url.netloc, '', '', '', ''))
            server = RefineServer(server)
        self.server = server
        if not project_id and not project_name:
            raise Exception('Missing Refine project ID and name; need at least one of those')
        if not project_name or not project_id:
            project_id, project_name = Refine(server).get_project_id_name(project_name or
                                                                          project_id)
        self.project_id = project_id
        self.project_name = project_name

    def do_raw(self, command, data):
        """Issue a command to the server & return a response object."""
        return self.server.urlopen(command, self.project_id, data)

    def do_json(self, command, data=None):
        """Issue a command to the server, parse & return decoded JSON."""
        return self.server.urlopen_json(command, project_id=self.project_id, data=data)


    def wait_until_idle(self, polling_delay=0.5):
        while True:
            response_json = self.do('get-processes')
            if 'processes' in response_json and len(response_json['processes']) > 0:
                time.sleep(polling_delay)
            else:
                return

    def apply_operations(self, file_path, wait=True):
        json = open(file_path).read()
        response_json = self.do('apply-operations', {'operations': json})
        if response_json['code'] == 'pending':
            if wait:
                self.wait_until_idle()
                return 'ok'
        return response_json['code'] # can be 'ok' or 'pending'
        
    def export(self, export_format='tsv'):
        """Return a fileobject of a project's data."""
        data = {
            'engine': Engine().as_json(),
            'format': export_format,
        }
        return self.do_raw(
            'export-rows/' + urllib.quote(self.project_name) + '.' + export_format, data)

    def export_rows(self, **kwargs):
        """Return an iterable of parsed rows of a project's data."""
        return csv.reader(self.export(**kwargs), dialect='excel-tab')

    def delete(self):
        response_json = self.do_json('delete-project')
        return 'code' in response_json and response_json['code'] == 'ok'
        
    def text_facet(self, facets=None, engine=None, mode='row-based'):
        if not engine:
            engine = Engine(facets, mode)
        response = self.do_json('compute-facets', {'engine': engine.as_json()})
        return FacetsResponse(response)