"""Exercise the app's real log-draining function without starting its global app."""
import ast
import os
import queue
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from typing import List

source=Path(__file__).resolve().parents[1]/'app/app.py'
tree=ast.parse(source.read_text(encoding='utf-8'))
function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='_stream_subprocess_to_logs')
namespace=dict(subprocess=subprocess,os=os,queue=queue,threading=threading,List=List)
exec(compile(ast.Module(body=[function],type_ignores=[]),str(source),'exec'),namespace)
stream_logs=namespace['_stream_subprocess_to_logs']


class SubprocessLoggingTests(unittest.TestCase):
    def test_unicode_survives_child_and_parent_encoding(self):
        state=dict(logs=[],process=None,cancel=False)
        code="print('\\u9b54\\u6cd5 \\u2014 \\u05e9\\u05dc\\u05d5\\u05dd')"
        result=stream_logs([sys.executable,'-c',code],str(source.parent),state)
        self.assertEqual(result,0)
        self.assertEqual(state['logs'],['\u9b54\u6cd5 \u2014 \u05e9\u05dc\u05d5\u05dd'])

    def test_log_limit_and_failed_exit_are_preserved(self):
        state=dict(logs=[],cancel=False)
        result=stream_logs([sys.executable,'-c',"print('first'); print('last'); raise SystemExit(3)"],str(source.parent),state,max_logs=1)
        self.assertEqual(result,3)
        self.assertEqual(state['logs'],['last'])


if __name__=='__main__':
    unittest.main()
