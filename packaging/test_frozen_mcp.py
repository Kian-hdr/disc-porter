"""Run the independent root MCP contract suite through the actual frozen helper."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import unittest
from mcp import StdioServerParameters

root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--helper',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
spec=importlib.util.spec_from_file_location('disc_porter_mcp_contract_tests',root/'tests/mcp/test_bridge.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
helper=a.helper.resolve()
def frozen_parameters(*args,**kwargs):
    env=kwargs.get('env',{}).copy()
    env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    env['PATH']='/usr/bin:/bin'
    return StdioServerParameters(command=str(helper),args=['mcp'],env=env)
module.StdioServerParameters=frozen_parameters
suite=unittest.defaultTestLoader.loadTestsFromTestCase(module.BridgeTests)
result=unittest.TextTestRunner(verbosity=2).run(suite)
record={'tests_run':result.testsRun,'passed':result.wasSuccessful(),'failures':len(result.failures),'errors':len(result.errors),'expected_tool_count':43,'transport':'actual frozen helper mcp over official SDK stdio','environment':'PATH=/usr/bin:/bin; no PYTHONPATH or PYTHONHOME','contract_suite':'tests/mcp/test_bridge.py'}
a.output.write_text(json.dumps(record,indent=2)+'\n')
raise SystemExit(0 if result.wasSuccessful() else 1)
