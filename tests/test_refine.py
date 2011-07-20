#!/usr/bin/env python
"""
test_refine.py

These tests require a connection to a Refine server either at
http://127.0.0.1:3333/ or by specifying environment variables
GOOGLE_REFINE_HOST and GOOGLE_REFINE_PORT.
"""

# Copyright (c) 2011 Paul Makepeace, Real Programmers. All rights reserved.

import unittest

from google.refine import refine
from tests import refinetest


class RefineServerTest(refinetest.RefineTestCase):
    def test_init(self):
        server_url = 'http://' + refine.REFINE_HOST
        if refine.REFINE_PORT != '80':
            server_url += ':' + refine.REFINE_PORT
        self.assertEqual(self.server.server, server_url)
        self.assertEqual(refine.RefineServer.url(), server_url)
        # strip trailing /
        server = refine.RefineServer('http://refine.example/')
        self.assertEqual(server.server, 'http://refine.example')

    def test_list_projects(self):
        projects = self.refine.list_projects()
        self.assertTrue(isinstance(projects, dict))

    def test_get_version(self):
        version_info = self.server.get_version()
        for item in ('revision', 'version', 'full_version', 'full_name'):
            self.assertTrue(item in version_info)

    def test_version(self):
        self.assertTrue(self.server.version in ('2.0', '2.1'))


class RefineTest(refinetest.RefineTestCase):
    project_file = 'duplicates.csv'

    def test_new_project(self):
        self.assertTrue(isinstance(self.project, refine.RefineProject))

    def test_wait_until_idle(self):
        self.project.wait_until_idle()  # should just return

    def test_get_models(self):
        self.assertEqual(self.project.key_column, 'email')
        self.assertTrue('email' in self.project.columns)
        self.assertTrue('email' in self.project.column_order)
        self.assertEqual(self.project.column_order['name'], 1)

    def test_delete_project(self):
        self.assertTrue(self.project.delete())

    def test_open_export(self):
        fp = refine.RefineProject(self.project.project_url()).export()
        line = fp.next()
        self.assertTrue('email' in line)
        fp.close()


if __name__ == '__main__':
    unittest.main()
